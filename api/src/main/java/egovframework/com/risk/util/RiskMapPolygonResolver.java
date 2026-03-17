package egovframework.com.risk.util;

import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Stream;

public final class RiskMapPolygonResolver {

    private static final ConcurrentHashMap<String, Path> SHP_PATH_CACHE = new ConcurrentHashMap<String, Path>();
    private static final ConcurrentHashMap<String, ShapefileIndex> SHAPEFILE_CACHE =
            new ConcurrentHashMap<String, ShapefileIndex>();

    private RiskMapPolygonResolver() {
    }

    public static void attachPolygons(String branchNm, List<Map<String, Object>> rows, int maxPointsPerRing) {
        if (rows == null || rows.isEmpty()) {
            return;
        }

        ShapefileIndex index = resolveIndex(branchNm);
        if (index == null) {
            return;
        }

        List<Long> bldgSeqs = new ArrayList<Long>();
        for (Map<String, Object> row : rows) {
            long bldgSeq = asLong(firstNonNull(row.get("bldgSeq"), row.get("BLDGSEQ")));
            if (bldgSeq > 0L) {
                bldgSeqs.add(Long.valueOf(bldgSeq));
            }
        }
        if (bldgSeqs.isEmpty()) {
            return;
        }

        Map<Long, Map<String, Object>> geometryBySeq = index.readPolygons(bldgSeqs, maxPointsPerRing);
        for (Map<String, Object> row : rows) {
            long bldgSeq = asLong(firstNonNull(row.get("bldgSeq"), row.get("BLDGSEQ")));
            Map<String, Object> geometry = geometryBySeq.get(Long.valueOf(bldgSeq));
            if (geometry != null) {
                row.putAll(geometry);
            }
        }
    }

    private static ShapefileIndex resolveIndex(String branchNm) {
        Path shpPath = resolveBranchShpPath(branchNm);
        if (shpPath == null) {
            return null;
        }
        String cacheKey = shpPath.toString();
        return SHAPEFILE_CACHE.computeIfAbsent(cacheKey, key -> {
            try {
                return new ShapefileIndex(Paths.get(key));
            } catch (IOException e) {
                return null;
            }
        });
    }

    private static Path resolveBranchShpPath(String branchNm) {
        if (branchNm == null || branchNm.trim().isEmpty()) {
            return null;
        }
        String normalizedBranchNm = branchNm.trim();
        if (SHP_PATH_CACHE.containsKey(normalizedBranchNm)) {
            return SHP_PATH_CACHE.get(normalizedBranchNm);
        }

        String expectedPrefix = "\uD1B5\uD569\uC704\uD5D8\uBD84\uC11D_" + normalizedBranchNm + "_";
        Path resultBaseDir = ProjectPathResolver.resolveFromProjectRoot("\uC0AC\uC5C5\uC18C\uBCC4 \uBD84\uC11D\uACB0\uACFC");
        Path found = null;
        if (!Files.isDirectory(resultBaseDir)) {
            return null;
        }
        try (Stream<Path> stream = Files.walk(resultBaseDir, 4)) {
            found = stream
                    .filter(Files::isRegularFile)
                    .filter(path -> path.getFileName().toString().startsWith(expectedPrefix))
                    .filter(path -> path.getFileName().toString().toLowerCase().endsWith(".shp"))
                    .max(Comparator.comparing(path -> path.getFileName().toString()))
                    .orElse(null);
        } catch (IOException e) {
            found = null;
        }

        if (found != null) {
            SHP_PATH_CACHE.put(normalizedBranchNm, found);
        }
        return found;
    }

    private static Object firstNonNull(Object left, Object right) {
        return left != null ? left : right;
    }

    private static long asLong(Object value) {
        if (value == null) {
            return 0L;
        }
        if (value instanceof Number) {
            return ((Number) value).longValue();
        }
        try {
            return Long.parseLong(String.valueOf(value));
        } catch (Exception e) {
            return 0L;
        }
    }

    private static final class ShapefileIndex {
        private final Path shpPath;
        private final int[] offsetsWords;
        private final int[] contentLengthWords;

        private ShapefileIndex(Path shpPath) throws IOException {
            this.shpPath = shpPath;
            Path shxPath = withExtension(shpPath, ".shx");
            byte[] shxBytes = Files.readAllBytes(shxPath);
            int recordCount = Math.max(0, (shxBytes.length - 100) / 8);
            this.offsetsWords = new int[recordCount];
            this.contentLengthWords = new int[recordCount];
            int pos = 100;
            for (int i = 0; i < recordCount; i++) {
                offsetsWords[i] = readBEInt(shxBytes, pos);
                contentLengthWords[i] = readBEInt(shxBytes, pos + 4);
                pos += 8;
            }
        }

        private Map<Long, Map<String, Object>> readPolygons(Collection<Long> bldgSeqs, int maxPointsPerRing) {
            Map<Long, Map<String, Object>> result = new HashMap<Long, Map<String, Object>>();
            try (RandomAccessFile shp = new RandomAccessFile(shpPath.toFile(), "r")) {
                for (Long bldgSeq : bldgSeqs) {
                    if (bldgSeq == null || bldgSeq.longValue() <= 0L) {
                        continue;
                    }
                    int recordIndex = (int) bldgSeq.longValue() - 1;
                    if (recordIndex < 0 || recordIndex >= offsetsWords.length) {
                        continue;
                    }
                    Map<String, Object> geometry = readSinglePolygon(shp, recordIndex, maxPointsPerRing);
                    if (geometry != null) {
                        result.put(bldgSeq, geometry);
                    }
                }
            } catch (IOException e) {
                return result;
            }
            return result;
        }

        private Map<String, Object> readSinglePolygon(RandomAccessFile shp, int recordIndex, int maxPointsPerRing)
                throws IOException {
            long offset = ((long) offsetsWords[recordIndex]) * 2L;
            int contentBytes = contentLengthWords[recordIndex] * 2;
            if (contentBytes <= 0) {
                return null;
            }

            shp.seek(offset + 8L);
            byte[] content = new byte[contentBytes];
            shp.readFully(content);

            int shapeType = readLEInt(content, 0);
            if (shapeType == 0) {
                return null;
            }
            if (shapeType != 5 && shapeType != 15 && shapeType != 25) {
                return null;
            }

            int numParts = readLEInt(content, 36);
            int numPoints = readLEInt(content, 40);
            if (numParts <= 0 || numPoints <= 0) {
                return null;
            }

            int partsPos = 44;
            int pointsPos = partsPos + (numParts * 4);
            if (pointsPos + (numPoints * 16) > content.length) {
                return null;
            }

            int[] partIndexes = new int[numParts];
            for (int i = 0; i < numParts; i++) {
                partIndexes[i] = readLEInt(content, partsPos + (i * 4));
            }

            List<List<double[]>> rings = new ArrayList<List<double[]>>();
            for (int part = 0; part < numParts; part++) {
                int start = partIndexes[part];
                int end = (part == numParts - 1) ? numPoints : partIndexes[part + 1];
                if (start < 0 || end <= start) {
                    continue;
                }
                List<double[]> ring = new ArrayList<double[]>();
                int step = computeStep(end - start, maxPointsPerRing);
                for (int i = start; i < end; i += step) {
                    int pointOffset = pointsPos + (i * 16);
                    ring.add(new double[] {
                            readLEDouble(content, pointOffset),
                            readLEDouble(content, pointOffset + 8)
                    });
                }
                int lastPointOffset = pointsPos + ((end - 1) * 16);
                appendClosingPointIfNeeded(ring,
                        readLEDouble(content, lastPointOffset),
                        readLEDouble(content, lastPointOffset + 8));
                if (ring.size() >= 4) {
                    rings.add(ring);
                }
            }

            if (rings.isEmpty()) {
                return null;
            }

            Map<String, Object> geometry = new LinkedHashMap<String, Object>();
            geometry.put("geomType", "Polygon");
            geometry.put("rings", rings);
            return geometry;
        }

        private int computeStep(int pointCount, int maxPointsPerRing) {
            if (maxPointsPerRing <= 0 || pointCount <= maxPointsPerRing) {
                return 1;
            }
            return Math.max(1, pointCount / maxPointsPerRing);
        }

        private void appendClosingPointIfNeeded(List<double[]> ring, double lastX, double lastY) {
            if (ring.isEmpty()) {
                return;
            }
            double[] first = ring.get(0);
            double[] last = ring.get(ring.size() - 1);
            if (last[0] != lastX || last[1] != lastY) {
                ring.add(new double[] { lastX, lastY });
                last = ring.get(ring.size() - 1);
            }
            if (last[0] != first[0] || last[1] != first[1]) {
                ring.add(new double[] { first[0], first[1] });
            }
        }
    }

    private static Path withExtension(Path path, String ext) {
        String name = path.getFileName().toString();
        int idx = name.lastIndexOf('.');
        String baseName = (idx >= 0) ? name.substring(0, idx) : name;
        return path.resolveSibling(baseName + ext);
    }

    private static int readBEInt(byte[] bytes, int offset) {
        return ((bytes[offset] & 0xff) << 24)
                | ((bytes[offset + 1] & 0xff) << 16)
                | ((bytes[offset + 2] & 0xff) << 8)
                | (bytes[offset + 3] & 0xff);
    }

    private static int readLEInt(byte[] bytes, int offset) {
        return (bytes[offset] & 0xff)
                | ((bytes[offset + 1] & 0xff) << 8)
                | ((bytes[offset + 2] & 0xff) << 16)
                | ((bytes[offset + 3] & 0xff) << 24);
    }

    private static double readLEDouble(byte[] bytes, int offset) {
        long bits = 0L;
        for (int i = 7; i >= 0; i--) {
            bits = (bits << 8) | (bytes[offset + i] & 0xffL);
        }
        return Double.longBitsToDouble(bits);
    }
}
