// Package main is the entry point for the NetSentinel flow collector.
package main

import (
	"os"
	"os/signal"
	"syscall"

	"github.com/netsentinel/collector/internal/config"
	"github.com/netsentinel/collector/internal/sender"
	"github.com/netsentinel/collector/internal/server"
	log "github.com/sirupsen/logrus"
)

// Version is set at build time
var Version = "dev"

func main() {
	// Load configuration
	cfg := config.Load()

	// Configure logging
	configureLogging(cfg)

	log.WithField("version", Version).Info("Starting NetSentinel Collector")

	// Validate configuration
	if err := cfg.Validate(); err != nil {
		log.WithError(err).Fatal("Invalid configuration")
	}

	// Create the appropriate sender backend
	var flowSender sender.Sender
	var err error

	switch cfg.OutputMode {
	case "http":
		flowSender = sender.NewHTTPSender(cfg)
		log.WithField("backend_url", cfg.BackendURL).Info("Using HTTP backend")

	case "postgres":
		flowSender, err = sender.NewPostgresSender(cfg)
		if err != nil {
			log.WithError(err).Fatal("Failed to create PostgreSQL sender")
		}
		log.Info("Using PostgreSQL backend")

	default:
		log.WithField("mode", cfg.OutputMode).Fatal("Unknown output mode")
	}

	// Create batch sender with backpressure handling
	batchSender := sender.NewBatchSender(cfg, flowSender)
	batchSender.Start()

	// Create UDP server
	udpServer := server.NewUDPServer(cfg, batchSender)
	if err := udpServer.Start(); err != nil {
		log.WithError(err).Fatal("Failed to start UDP server")
	}

	// Create health server
	healthServer := server.NewHealthServer(cfg, udpServer, batchSender)
	if err := healthServer.Start(); err != nil {
		log.WithError(err).Fatal("Failed to start health server")
	}

	log.WithFields(log.Fields{
		"udp_port":    cfg.UDPPort,
		"health_port": cfg.HealthPort,
		"batch_size":  cfg.BatchSize,
		"queue_size":  cfg.QueueSize,
	}).Info("Collector is ready")

	// Wait for shutdown signal
	waitForShutdown()

	// Graceful shutdown
	log.Info("Shutting down...")

	udpServer.Stop()
	healthServer.Stop()
	batchSender.Stop()

	log.Info("Collector stopped")
}

// configureLogging sets up the logger based on configuration.
func configureLogging(cfg *config.Config) {
	// Set log level
	level, err := log.ParseLevel(cfg.LogLevel)
	if err != nil {
		level = log.InfoLevel
	}
	log.SetLevel(level)

	// Set JSON format if configured
	if cfg.LogJSON {
		log.SetFormatter(&log.JSONFormatter{
			TimestampFormat: "2006-01-02T15:04:05.000Z07:00",
		})
	} else {
		log.SetFormatter(&log.TextFormatter{
			FullTimestamp:   true,
			TimestampFormat: "2006-01-02 15:04:05",
		})
	}

	log.SetOutput(os.Stdout)
}

// waitForShutdown blocks until a termination signal is received.
func waitForShutdown() {
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigChan
	log.WithField("signal", sig).Info("Received shutdown signal")
}
