package config

import (
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestLoad_Defaults(t *testing.T) {
	// Clear any env vars that might affect the test
	envVars := []string{
		"COLLECTOR_UDP_PORT",
		"COLLECTOR_BATCH_SIZE",
		"COLLECTOR_QUEUE_SIZE",
		"COLLECTOR_OUTPUT_MODE",
		"BACKEND_URL",
		"DATABASE_URL",
	}
	for _, v := range envVars {
		os.Unsetenv(v)
	}

	cfg := Load()

	assert.Equal(t, 2055, cfg.UDPPort)
	assert.Equal(t, 100, cfg.BatchSize)
	assert.Equal(t, 10000, cfg.QueueSize)
	assert.Equal(t, 1*time.Second, cfg.FlushInterval)
	assert.Equal(t, "http", cfg.OutputMode)
	assert.Equal(t, "http://localhost:8000", cfg.BackendURL)
	assert.Equal(t, 8080, cfg.HealthPort)
	assert.Equal(t, "info", cfg.LogLevel)
}

func TestLoad_FromEnv(t *testing.T) {
	// Set custom values
	os.Setenv("COLLECTOR_UDP_PORT", "9999")
	os.Setenv("COLLECTOR_BATCH_SIZE", "500")
	os.Setenv("COLLECTOR_FLUSH_INTERVAL", "5s")
	os.Setenv("COLLECTOR_OUTPUT_MODE", "postgres")
	os.Setenv("DATABASE_URL", "postgres://user:pass@localhost/db")
	os.Setenv("LOG_LEVEL", "debug")
	os.Setenv("LOG_JSON", "true")

	defer func() {
		os.Unsetenv("COLLECTOR_UDP_PORT")
		os.Unsetenv("COLLECTOR_BATCH_SIZE")
		os.Unsetenv("COLLECTOR_FLUSH_INTERVAL")
		os.Unsetenv("COLLECTOR_OUTPUT_MODE")
		os.Unsetenv("DATABASE_URL")
		os.Unsetenv("LOG_LEVEL")
		os.Unsetenv("LOG_JSON")
	}()

	cfg := Load()

	assert.Equal(t, 9999, cfg.UDPPort)
	assert.Equal(t, 500, cfg.BatchSize)
	assert.Equal(t, 5*time.Second, cfg.FlushInterval)
	assert.Equal(t, "postgres", cfg.OutputMode)
	assert.Equal(t, "postgres://user:pass@localhost/db", cfg.PostgresURL)
	assert.Equal(t, "debug", cfg.LogLevel)
	assert.True(t, cfg.LogJSON)
}

func TestConfig_Validate_HTTPMode(t *testing.T) {
	cfg := &Config{
		UDPPort:    2055,
		BatchSize:  100,
		QueueSize:  1000,
		OutputMode: "http",
		BackendURL: "http://localhost:8000",
	}

	err := cfg.Validate()
	assert.NoError(t, err)
}

func TestConfig_Validate_HTTPMode_MissingURL(t *testing.T) {
	cfg := &Config{
		UDPPort:    2055,
		BatchSize:  100,
		QueueSize:  1000,
		OutputMode: "http",
		BackendURL: "", // Missing
	}

	err := cfg.Validate()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "BackendURL")
}

func TestConfig_Validate_PostgresMode(t *testing.T) {
	cfg := &Config{
		UDPPort:     2055,
		BatchSize:   100,
		QueueSize:   1000,
		OutputMode:  "postgres",
		PostgresURL: "postgres://localhost/db",
	}

	err := cfg.Validate()
	assert.NoError(t, err)
}

func TestConfig_Validate_PostgresMode_MissingURL(t *testing.T) {
	cfg := &Config{
		UDPPort:     2055,
		BatchSize:   100,
		QueueSize:   1000,
		OutputMode:  "postgres",
		PostgresURL: "", // Missing
	}

	err := cfg.Validate()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "PostgresURL")
}

func TestConfig_Validate_InvalidOutputMode(t *testing.T) {
	cfg := &Config{
		UDPPort:    2055,
		BatchSize:  100,
		QueueSize:  1000,
		OutputMode: "invalid",
	}

	err := cfg.Validate()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "OutputMode")
}

func TestConfig_Validate_InvalidPort(t *testing.T) {
	cfg := &Config{
		UDPPort:    99999, // Invalid
		BatchSize:  100,
		QueueSize:  1000,
		OutputMode: "http",
		BackendURL: "http://localhost:8000",
	}

	err := cfg.Validate()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "UDPPort")
}

func TestConfig_Validate_InvalidBatchSize(t *testing.T) {
	cfg := &Config{
		UDPPort:    2055,
		BatchSize:  0, // Invalid
		QueueSize:  1000,
		OutputMode: "http",
		BackendURL: "http://localhost:8000",
	}

	err := cfg.Validate()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "BatchSize")
}

func TestGetEnvBool(t *testing.T) {
	tests := []struct {
		value    string
		expected bool
	}{
		{"true", true},
		{"TRUE", true},
		{"True", true},
		{"1", true},
		{"yes", true},
		{"YES", true},
		{"false", false},
		{"0", false},
		{"no", false},
		{"", false}, // Default
	}

	for _, tt := range tests {
		t.Run(tt.value, func(t *testing.T) {
			os.Setenv("TEST_BOOL", tt.value)
			defer os.Unsetenv("TEST_BOOL")

			result := getEnvBool("TEST_BOOL", false)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestGetEnvDuration(t *testing.T) {
	tests := []struct {
		value    string
		expected time.Duration
	}{
		{"1s", 1 * time.Second},
		{"5m", 5 * time.Minute},
		{"100ms", 100 * time.Millisecond},
		{"invalid", 10 * time.Second}, // Should return default
		{"", 10 * time.Second},        // Should return default
	}

	for _, tt := range tests {
		t.Run(tt.value, func(t *testing.T) {
			os.Setenv("TEST_DURATION", tt.value)
			defer os.Unsetenv("TEST_DURATION")

			result := getEnvDuration("TEST_DURATION", 10*time.Second)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestConfigError_Error(t *testing.T) {
	err := &ConfigError{
		Field:   "TestField",
		Message: "is required",
	}

	assert.Equal(t, "config error: TestField is required", err.Error())
}
