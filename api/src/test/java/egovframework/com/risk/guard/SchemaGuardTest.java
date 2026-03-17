package egovframework.com.risk.guard;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.regex.Pattern;

import org.junit.Test;

public class SchemaGuardTest {

    private static final Pattern H2_WEATHER_UNIQUE_PATTERN = Pattern.compile(
            "CREATE\\s+UNIQUE\\s+INDEX\\s+IF\\s+NOT\\s+EXISTS\\s+\\w+\\s+ON\\s+TB_WEATHER_RISK\\s*\\(\\s*RISK_DATE\\s*,\\s*REGION_CD\\s*\\)",
            Pattern.CASE_INSENSITIVE | Pattern.DOTALL);

    private static final Pattern ORACLE_WEATHER_UNIQUE_PATTERN = Pattern.compile(
            "CONSTRAINT\\s+UK_WEATHER_RISK\\s+UNIQUE\\s*\\(\\s*RISK_DATE\\s*,\\s*REGION_CD\\s*\\)",
            Pattern.CASE_INSENSITIVE | Pattern.DOTALL);

    @Test
    public void h2WeatherUniqueKeyMustMatchOracleShape() throws Exception {
        String h2Sql = readUtf8("src/main/resources/egovframework/spring/h2/04_create_weather_tables.sql");
        String oracleSql = readUtf8("../db/04_create_weather_tables.sql");

        assertTrue("H2 unique key must be (RISK_DATE, REGION_CD)", H2_WEATHER_UNIQUE_PATTERN.matcher(h2Sql).find());
        assertTrue("Oracle unique key must be (RISK_DATE, REGION_CD)", ORACLE_WEATHER_UNIQUE_PATTERN.matcher(oracleSql).find());
    }

    @Test
    public void weatherAlertZoneFileMustBeExternalized() throws Exception {
        String source = readUtf8("src/main/java/egovframework/com/risk/service/impl/WeatherUpdateServiceImpl.java");

        assertFalse("Workspace absolute path must not be hardcoded",
                source.contains("C:\\\\Users\\\\user\\\\Downloads\\\\kescoaitest\\\\\\uae30\\uc0c1\\ud2b9\\ubcf4\\uad6c\\uc5ed.txt"));
        assertTrue(source.contains("ALERT_ZONE_FILE_PROPERTY"));
        assertTrue(source.contains("ALERT_ZONE_FILE_ENV"));
        assertTrue(source.contains("ALERT_ZONE_CLASSPATH"));

        Path classpathFile = Paths.get("src/main/resources/egovframework/spring/alert-zones.csv");
        assertTrue("Classpath fallback file must exist: " + classpathFile, Files.exists(classpathFile));
    }

    @Test
    public void legacyOracleMigrationScriptMustExist() throws Exception {
        Path migration = Paths.get("../db/09_migrate_from_legacy_schema_oracle.sql");
        assertTrue("Migration script must exist: " + migration, Files.exists(migration));

        String sql = readUtf8(migration.toString());
        assertTrue("Migration must patch A1~A30 family", sql.contains("A30"));
        assertTrue("Migration must standardize weather unique key", sql.contains("UK_WEATHER_RISK"));
        assertTrue("Migration must recreate combined view", sql.contains("@@06_combined_queries.sql"));
    }

    private String readUtf8(String relativePath) throws Exception {
        Path path = Paths.get(relativePath);
        return new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
    }
}
