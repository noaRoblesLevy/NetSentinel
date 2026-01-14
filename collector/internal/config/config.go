// Package config provides configuration management for the collector service.
package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

// Config holds all configuration for the collector service.
type Config struct {
	// UDP Collector settings
	UDPPort     int
	UDPBufferSize int

	// Batching settings
	BatchSize     int
	FlushInterval time.Duration

	// Backpressure settings
	QueueSize       int
	MaxRetries      int
	RetryBackoff    time.Duration
	MaxRetryBackoff time.Duration

	// Output settings
	OutputMode string // "http" or "postgres"

	// HTTP Backend settings (when OutputMode = "http")
	BackendURL    string
	CollectorKey  string
	HTTPTimeout   time.Duration

	// Postgres settings (when OutputMode = "postgres")
	PostgresURL string

	// Site configuration
	DefaultSiteID string

	// HTTP Health server settings
	HealthPort int

	// Logging
	LogLevel string
	LogJSON  bool
}

// Load creates a Config from environment variables with sensible defaults.
func Load() *Config {
	return &Config{
		// UDP settings
		UDPPort:       getEnvInt("COLLECTOR_UDP_PORT", 2055),
		UDPBufferSize: getEnvInt("COLLECTOR_UDP_BUFFER_SIZE", 65535),

		// Batching
		BatchSize:     getEnvInt("COLLECTOR_BATCH_SIZE", 100),
		FlushInterval: getEnvDuration("COLLECTOR_FLUSH_INTERVAL", 1*time.Second),

		// Backpressure
		QueueSize:       getEnvInt("COLLECTOR_QUEUE_SIZE", 10000),
		MaxRetries:      getEnvInt("COLLECTOR_MAX_RETRIES", 5),
		RetryBackoff:    getEnvDuration("COLLECTOR_RETRY_BACKOFF", 100*time.Millisecond),
		MaxRetryBackoff: getEnvDuration("COLLECTOR_MAX_RETRY_BACKOFF", 30*time.Second),

		// Output
		OutputMode: getEnvString("COLLECTOR_OUTPUT_MODE", "http"),

		// HTTP Backend
		BackendURL:   getEnvString("BACKEND_URL", "http://localhost:8000"),
		CollectorKey: getEnvString("COLLECTOR_API_KEY", ""),
		HTTPTimeout:  getEnvDuration("COLLECTOR_HTTP_TIMEOUT", 10*time.Second),

		// Postgres
		PostgresURL: getEnvString("DATABASE_URL", ""),

		// Site
		DefaultSiteID: getEnvString("DEFAULT_SITE_ID", ""),

		// Health server
		HealthPort: getEnvInt("COLLECTOR_HEALTH_PORT", 8080),

		// Logging
		LogLevel: getEnvString("LOG_LEVEL", "info"),
		LogJSON:  getEnvBool("LOG_JSON", false),
	}
}

// Validate checks if the configuration is valid.
func (c *Config) Validate() error {
	if c.UDPPort < 1 || c.UDPPort > 65535 {
		return &ConfigError{Field: "UDPPort", Message: "must be between 1 and 65535"}
	}
	if c.BatchSize < 1 {
		return &ConfigError{Field: "BatchSize", Message: "must be at least 1"}
	}
	if c.QueueSize < 1 {
		return &ConfigError{Field: "QueueSize", Message: "must be at least 1"}
	}

	switch c.OutputMode {
	case "http":
		if c.BackendURL == "" {
			return &ConfigError{Field: "BackendURL", Message: "required when OutputMode is http"}
		}
	case "postgres":
		if c.PostgresURL == "" {
			return &ConfigError{Field: "PostgresURL", Message: "required when OutputMode is postgres"}
		}
	default:
		return &ConfigError{Field: "OutputMode", Message: "must be 'http' or 'postgres'"}
	}

	return nil
}

// ConfigError represents a configuration validation error.
type ConfigError struct {
	Field   string
	Message string
}

func (e *ConfigError) Error() string {
	return "config error: " + e.Field + " " + e.Message
}

// Helper functions for reading environment variables

func getEnvString(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

func getEnvInt(key string, defaultVal int) int {
	if val := os.Getenv(key); val != "" {
		if i, err := strconv.Atoi(val); err == nil {
			return i
		}
	}
	return defaultVal
}

func getEnvBool(key string, defaultVal bool) bool {
	if val := os.Getenv(key); val != "" {
		val = strings.ToLower(val)
		return val == "true" || val == "1" || val == "yes"
	}
	return defaultVal
}

func getEnvDuration(key string, defaultVal time.Duration) time.Duration {
	if val := os.Getenv(key); val != "" {
		if d, err := time.ParseDuration(val); err == nil {
			return d
		}
	}
	return defaultVal
}
