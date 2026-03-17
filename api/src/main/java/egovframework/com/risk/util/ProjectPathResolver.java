package egovframework.com.risk.util;

import java.nio.file.Path;
import java.nio.file.Paths;

public final class ProjectPathResolver {

    private static final String PROJECT_ROOT_PROPERTY = "risk.project.root";
    private static final String PROJECT_ROOT_ENV = "RISK_PROJECT_ROOT";

    private ProjectPathResolver() {
    }

    public static Path resolveProjectRoot() {
        String byProperty = trimToNull(System.getProperty(PROJECT_ROOT_PROPERTY));
        if (byProperty != null) {
            return Paths.get(byProperty).toAbsolutePath().normalize();
        }

        String byEnv = trimToNull(System.getenv(PROJECT_ROOT_ENV));
        if (byEnv != null) {
            return Paths.get(byEnv).toAbsolutePath().normalize();
        }

        return Paths.get("").toAbsolutePath().normalize();
    }

    public static Path resolveFromProjectRoot(String first, String... more) {
        Path path = resolveProjectRoot().resolve(Paths.get(first, more)).normalize();
        return path;
    }

    private static String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}
