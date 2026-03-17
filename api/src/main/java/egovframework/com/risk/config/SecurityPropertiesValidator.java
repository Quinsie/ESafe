package egovframework.com.risk.config;

import javax.annotation.PostConstruct;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class SecurityPropertiesValidator {

    @Value("${risk.security.admin.username:}")
    private String adminUsername;

    @Value("${risk.security.admin.password:}")
    private String adminPassword;

    @Value("${risk.security.user.username:}")
    private String userUsername;

    @Value("${risk.security.user.password:}")
    private String userPassword;

    @PostConstruct
    public void validate() {
        ensureProvided("risk.security.admin.username", adminUsername);
        ensureProvided("risk.security.admin.password", adminPassword);
        ensureProvided("risk.security.user.username", userUsername);
        ensureProvided("risk.security.user.password", userPassword);
    }

    private void ensureProvided(String key, String value) {
        if (value == null) {
            throw new IllegalStateException("Missing required security property: " + key);
        }

        String normalized = value.trim();
        if (normalized.isEmpty() || normalized.startsWith("CHANGE_ME_")) {
            throw new IllegalStateException("Invalid security property. Replace placeholder value: " + key);
        }
    }
}
