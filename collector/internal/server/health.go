// Package server provides the UDP server and HTTP health endpoints.
package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"runtime"
	"time"

	"github.com/netsentinel/collector/internal/config"
	"github.com/netsentinel/collector/internal/sender"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	log "github.com/sirupsen/logrus"
)

// HealthServer provides HTTP endpoints for health checks and metrics.
type HealthServer struct {
	cfg         *config.Config
	httpServer  *http.Server
	udpServer   *UDPServer
	batchSender *sender.BatchSender
	startTime   time.Time

	// Prometheus metrics
	packetsTotal    prometheus.Counter
	flowsTotal      prometheus.Counter
	flowsDropped    prometheus.Counter
	batchesSent     prometheus.Counter
	batchesFailed   prometheus.Counter
	queueDepth      prometheus.Gauge
	parseErrors     prometheus.Counter
}

// NewHealthServer creates a new health server.
func NewHealthServer(cfg *config.Config, udpServer *UDPServer, batchSender *sender.BatchSender) *HealthServer {
	hs := &HealthServer{
		cfg:         cfg,
		udpServer:   udpServer,
		batchSender: batchSender,
		startTime:   time.Now(),
	}

	// Initialize Prometheus metrics
	hs.initMetrics()

	return hs
}

// initMetrics initializes Prometheus metrics.
func (hs *HealthServer) initMetrics() {
	hs.packetsTotal = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "netsentinel_collector_packets_total",
		Help: "Total number of UDP packets received",
	})

	hs.flowsTotal = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "netsentinel_collector_flows_total",
		Help: "Total number of flow records processed",
	})

	hs.flowsDropped = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "netsentinel_collector_flows_dropped_total",
		Help: "Total number of flow records dropped due to backpressure",
	})

	hs.batchesSent = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "netsentinel_collector_batches_sent_total",
		Help: "Total number of batches successfully sent",
	})

	hs.batchesFailed = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "netsentinel_collector_batches_failed_total",
		Help: "Total number of batches that failed to send",
	})

	hs.queueDepth = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "netsentinel_collector_queue_depth",
		Help: "Current depth of the flow processing queue",
	})

	hs.parseErrors = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "netsentinel_collector_parse_errors_total",
		Help: "Total number of packet parse errors",
	})

	// Register metrics
	prometheus.MustRegister(
		hs.packetsTotal,
		hs.flowsTotal,
		hs.flowsDropped,
		hs.batchesSent,
		hs.batchesFailed,
		hs.queueDepth,
		hs.parseErrors,
	)
}

// Start begins the HTTP health server.
func (hs *HealthServer) Start() error {
	mux := http.NewServeMux()

	// Health check endpoint
	mux.HandleFunc("/health", hs.handleHealth)
	mux.HandleFunc("/healthz", hs.handleHealth) // Kubernetes style

	// Readiness check
	mux.HandleFunc("/ready", hs.handleReady)
	mux.HandleFunc("/readyz", hs.handleReady)

	// Detailed stats endpoint
	mux.HandleFunc("/stats", hs.handleStats)

	// Prometheus metrics endpoint
	mux.Handle("/metrics", promhttp.Handler())

	hs.httpServer = &http.Server{
		Addr:         fmt.Sprintf(":%d", hs.cfg.HealthPort),
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
	}

	log.WithField("port", hs.cfg.HealthPort).Info("Health server started")

	go func() {
		if err := hs.httpServer.ListenAndServe(); err != http.ErrServerClosed {
			log.WithError(err).Error("Health server error")
		}
	}()

	// Start metrics updater
	go hs.metricsUpdater()

	return nil
}

// metricsUpdater periodically updates Prometheus metrics from internal stats.
func (hs *HealthServer) metricsUpdater() {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	var lastPackets, lastFlows, lastDropped, lastBatchesSent, lastBatchesFailed, lastParseErrors uint64

	for range ticker.C {
		// Get current stats
		udpStats := hs.udpServer.Stats()
		senderStats := hs.batchSender.Stats()

		// Update counters (delta since last update)
		currentPackets := udpStats["packets_received"].(uint64)
		if currentPackets > lastPackets {
			hs.packetsTotal.Add(float64(currentPackets - lastPackets))
			lastPackets = currentPackets
		}

		currentFlows := senderStats["flows_sent"]
		if currentFlows > lastFlows {
			hs.flowsTotal.Add(float64(currentFlows - lastFlows))
			lastFlows = currentFlows
		}

		currentDropped := senderStats["flows_dropped"]
		if currentDropped > lastDropped {
			hs.flowsDropped.Add(float64(currentDropped - lastDropped))
			lastDropped = currentDropped
		}

		currentBatchesSent := senderStats["batches_sent"]
		if currentBatchesSent > lastBatchesSent {
			hs.batchesSent.Add(float64(currentBatchesSent - lastBatchesSent))
			lastBatchesSent = currentBatchesSent
		}

		currentBatchesFailed := senderStats["batches_failed"]
		if currentBatchesFailed > lastBatchesFailed {
			hs.batchesFailed.Add(float64(currentBatchesFailed - lastBatchesFailed))
			lastBatchesFailed = currentBatchesFailed
		}

		currentParseErrors := udpStats["parse_errors"].(uint64)
		if currentParseErrors > lastParseErrors {
			hs.parseErrors.Add(float64(currentParseErrors - lastParseErrors))
			lastParseErrors = currentParseErrors
		}

		// Update gauges
		hs.queueDepth.Set(float64(senderStats["queue_depth"]))
	}
}

// handleHealth handles the health check endpoint.
func (hs *HealthServer) handleHealth(w http.ResponseWriter, r *http.Request) {
	status := "healthy"
	httpStatus := http.StatusOK

	if !hs.udpServer.IsRunning() {
		status = "unhealthy"
		httpStatus = http.StatusServiceUnavailable
	}

	response := map[string]interface{}{
		"status":    status,
		"timestamp": time.Now().UTC().Format(time.RFC3339),
		"uptime":    time.Since(hs.startTime).String(),
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(httpStatus)
	json.NewEncoder(w).Encode(response)
}

// handleReady handles the readiness check endpoint.
func (hs *HealthServer) handleReady(w http.ResponseWriter, r *http.Request) {
	ready := hs.udpServer.IsRunning()

	response := map[string]interface{}{
		"ready":     ready,
		"timestamp": time.Now().UTC().Format(time.RFC3339),
	}

	httpStatus := http.StatusOK
	if !ready {
		httpStatus = http.StatusServiceUnavailable
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(httpStatus)
	json.NewEncoder(w).Encode(response)
}

// handleStats handles the detailed stats endpoint.
func (hs *HealthServer) handleStats(w http.ResponseWriter, r *http.Request) {
	udpStats := hs.udpServer.Stats()
	senderStats := hs.batchSender.Stats()

	// Memory stats
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)

	response := map[string]interface{}{
		"timestamp": time.Now().UTC().Format(time.RFC3339),
		"uptime":    time.Since(hs.startTime).String(),
		"uptime_seconds": time.Since(hs.startTime).Seconds(),

		"udp": udpStats,
		"sender": senderStats,

		"runtime": map[string]interface{}{
			"goroutines":   runtime.NumGoroutine(),
			"heap_alloc":   memStats.HeapAlloc,
			"heap_sys":     memStats.HeapSys,
			"gc_cycles":    memStats.NumGC,
			"go_version":   runtime.Version(),
		},

		"config": map[string]interface{}{
			"udp_port":       hs.cfg.UDPPort,
			"batch_size":     hs.cfg.BatchSize,
			"flush_interval": hs.cfg.FlushInterval.String(),
			"queue_size":     hs.cfg.QueueSize,
			"output_mode":    hs.cfg.OutputMode,
		},
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

// Stop gracefully shuts down the health server.
func (hs *HealthServer) Stop() {
	log.Info("Stopping health server...")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	hs.httpServer.Shutdown(ctx)
	log.Info("Health server stopped")
}
