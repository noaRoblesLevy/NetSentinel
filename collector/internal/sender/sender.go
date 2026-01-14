// Package sender provides output backends for sending flow records.
package sender

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/google/uuid"
	"github.com/netsentinel/collector/internal/config"
	"github.com/netsentinel/collector/pkg/flow"
	log "github.com/sirupsen/logrus"
)

// Sender defines the interface for flow record output backends.
type Sender interface {
	Send(ctx context.Context, batch *flow.Batch) error
	Close() error
	Name() string
}

// BatchSender handles batching, backpressure, and retry logic for sending flows.
type BatchSender struct {
	cfg        *config.Config
	sender     Sender
	inputChan  chan *flow.Record
	batchChan  chan *flow.Batch
	wg         sync.WaitGroup
	ctx        context.Context
	cancel     context.CancelFunc

	// Metrics
	flowsReceived  atomic.Uint64
	flowsSent      atomic.Uint64
	flowsDropped   atomic.Uint64
	batchesSent    atomic.Uint64
	batchesFailed  atomic.Uint64
	retryCount     atomic.Uint64

	// State
	currentBatch   []*flow.Record
	batchMu        sync.Mutex
	lastFlush      time.Time
}

// NewBatchSender creates a new BatchSender with the specified backend.
func NewBatchSender(cfg *config.Config, sender Sender) *BatchSender {
	ctx, cancel := context.WithCancel(context.Background())

	bs := &BatchSender{
		cfg:        cfg,
		sender:     sender,
		inputChan:  make(chan *flow.Record, cfg.QueueSize),
		batchChan:  make(chan *flow.Batch, cfg.QueueSize/cfg.BatchSize+1),
		ctx:        ctx,
		cancel:     cancel,
		currentBatch: make([]*flow.Record, 0, cfg.BatchSize),
		lastFlush:  time.Now(),
	}

	return bs
}

// Start begins the batching and sending goroutines.
func (bs *BatchSender) Start() {
	// Batcher goroutine - collects flows into batches
	bs.wg.Add(1)
	go bs.batcherLoop()

	// Sender goroutine - sends batches with retry
	bs.wg.Add(1)
	go bs.senderLoop()

	// Flush timer goroutine
	bs.wg.Add(1)
	go bs.flushTimerLoop()

	log.WithFields(log.Fields{
		"backend":        bs.sender.Name(),
		"batch_size":     bs.cfg.BatchSize,
		"flush_interval": bs.cfg.FlushInterval,
		"queue_size":     bs.cfg.QueueSize,
	}).Info("BatchSender started")
}

// Submit adds a flow record to the processing queue.
// Returns false if the queue is full (backpressure).
func (bs *BatchSender) Submit(rec *flow.Record) bool {
	select {
	case bs.inputChan <- rec:
		bs.flowsReceived.Add(1)
		return true
	default:
		// Queue is full - backpressure
		bs.flowsDropped.Add(1)
		return false
	}
}

// SubmitBlocking adds a flow record, blocking if the queue is full.
func (bs *BatchSender) SubmitBlocking(ctx context.Context, rec *flow.Record) error {
	select {
	case bs.inputChan <- rec:
		bs.flowsReceived.Add(1)
		return nil
	case <-ctx.Done():
		return ctx.Err()
	case <-bs.ctx.Done():
		return fmt.Errorf("sender shutting down")
	}
}

// batcherLoop collects flows from inputChan and creates batches.
func (bs *BatchSender) batcherLoop() {
	defer bs.wg.Done()

	for {
		select {
		case rec, ok := <-bs.inputChan:
			if !ok {
				// Channel closed, flush remaining
				bs.flushBatch()
				return
			}
			bs.addToBatch(rec)

		case <-bs.ctx.Done():
			bs.flushBatch()
			return
		}
	}
}

// addToBatch adds a record to the current batch and flushes if full.
func (bs *BatchSender) addToBatch(rec *flow.Record) {
	bs.batchMu.Lock()
	defer bs.batchMu.Unlock()

	bs.currentBatch = append(bs.currentBatch, rec)

	if len(bs.currentBatch) >= bs.cfg.BatchSize {
		bs.flushBatchLocked()
	}
}

// flushBatch flushes the current batch to the send queue.
func (bs *BatchSender) flushBatch() {
	bs.batchMu.Lock()
	defer bs.batchMu.Unlock()
	bs.flushBatchLocked()
}

// flushBatchLocked flushes the current batch (must hold batchMu).
func (bs *BatchSender) flushBatchLocked() {
	if len(bs.currentBatch) == 0 {
		return
	}

	// Determine site ID and exporter ID from first record
	siteID := bs.cfg.DefaultSiteID
	exporterID := ""
	if len(bs.currentBatch) > 0 {
		if bs.currentBatch[0].SiteID != "" {
			siteID = bs.currentBatch[0].SiteID
		}
		exporterID = bs.currentBatch[0].ExporterID
	}

	batch := &flow.Batch{
		SiteID:     siteID,
		ExporterID: exporterID,
		Flows:      bs.currentBatch,
		BatchID:    uuid.New().String(),
		Timestamp:  time.Now(),
	}

	// Try to send to batch channel (non-blocking)
	select {
	case bs.batchChan <- batch:
		// Successfully queued
	default:
		// Batch queue full - drop oldest batch or this one
		log.Warn("Batch queue full, dropping batch")
		bs.flowsDropped.Add(uint64(len(bs.currentBatch)))
	}

	// Reset batch
	bs.currentBatch = make([]*flow.Record, 0, bs.cfg.BatchSize)
	bs.lastFlush = time.Now()
}

// flushTimerLoop periodically flushes incomplete batches.
func (bs *BatchSender) flushTimerLoop() {
	defer bs.wg.Done()

	ticker := time.NewTicker(bs.cfg.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			bs.batchMu.Lock()
			if len(bs.currentBatch) > 0 && time.Since(bs.lastFlush) >= bs.cfg.FlushInterval {
				bs.flushBatchLocked()
			}
			bs.batchMu.Unlock()

		case <-bs.ctx.Done():
			return
		}
	}
}

// senderLoop sends batches to the backend with retry logic.
func (bs *BatchSender) senderLoop() {
	defer bs.wg.Done()

	for {
		select {
		case batch, ok := <-bs.batchChan:
			if !ok {
				return
			}
			bs.sendWithRetry(batch)

		case <-bs.ctx.Done():
			// Drain remaining batches
			for {
				select {
				case batch := <-bs.batchChan:
					bs.sendWithRetry(batch)
				default:
					return
				}
			}
		}
	}
}

// sendWithRetry sends a batch with exponential backoff retry.
func (bs *BatchSender) sendWithRetry(batch *flow.Batch) {
	backoff := bs.cfg.RetryBackoff

	for attempt := 0; attempt <= bs.cfg.MaxRetries; attempt++ {
		ctx, cancel := context.WithTimeout(bs.ctx, bs.cfg.HTTPTimeout)
		err := bs.sender.Send(ctx, batch)
		cancel()

		if err == nil {
			bs.flowsSent.Add(uint64(len(batch.Flows)))
			bs.batchesSent.Add(1)
			return
		}

		bs.retryCount.Add(1)

		if attempt < bs.cfg.MaxRetries {
			log.WithFields(log.Fields{
				"attempt":  attempt + 1,
				"max":      bs.cfg.MaxRetries,
				"backoff":  backoff,
				"error":    err,
				"batch_id": batch.BatchID,
			}).Warn("Send failed, retrying")

			select {
			case <-time.After(backoff):
				// Exponential backoff
				backoff *= 2
				if backoff > bs.cfg.MaxRetryBackoff {
					backoff = bs.cfg.MaxRetryBackoff
				}
			case <-bs.ctx.Done():
				bs.flowsDropped.Add(uint64(len(batch.Flows)))
				bs.batchesFailed.Add(1)
				return
			}
		}
	}

	// All retries exhausted
	log.WithFields(log.Fields{
		"batch_id":    batch.BatchID,
		"flow_count":  len(batch.Flows),
	}).Error("Batch send failed after all retries")
	bs.flowsDropped.Add(uint64(len(batch.Flows)))
	bs.batchesFailed.Add(1)
}

// Stop gracefully shuts down the BatchSender.
func (bs *BatchSender) Stop() {
	log.Info("Stopping BatchSender...")
	bs.cancel()
	close(bs.inputChan)
	bs.wg.Wait()
	close(bs.batchChan)
	bs.sender.Close()
	log.Info("BatchSender stopped")
}

// Stats returns current metrics.
func (bs *BatchSender) Stats() map[string]uint64 {
	return map[string]uint64{
		"flows_received":  bs.flowsReceived.Load(),
		"flows_sent":      bs.flowsSent.Load(),
		"flows_dropped":   bs.flowsDropped.Load(),
		"batches_sent":    bs.batchesSent.Load(),
		"batches_failed":  bs.batchesFailed.Load(),
		"retry_count":     bs.retryCount.Load(),
		"queue_depth":     uint64(len(bs.inputChan)),
		"batch_queue_depth": uint64(len(bs.batchChan)),
	}
}

// QueueDepth returns the current queue depth (for backpressure monitoring).
func (bs *BatchSender) QueueDepth() int {
	return len(bs.inputChan)
}

// HTTPSender sends flow batches to the backend API via HTTP.
type HTTPSender struct {
	client     *http.Client
	url        string
	apiKey     string
}

// NewHTTPSender creates a new HTTP sender.
func NewHTTPSender(cfg *config.Config) *HTTPSender {
	return &HTTPSender{
		client: &http.Client{
			Timeout: cfg.HTTPTimeout,
		},
		url:    cfg.BackendURL + "/api/v1/flows/ingest",
		apiKey: cfg.CollectorKey,
	}
}

// Send sends a batch to the backend API.
func (h *HTTPSender) Send(ctx context.Context, batch *flow.Batch) error {
	data, err := json.Marshal(batch)
	if err != nil {
		return fmt.Errorf("marshal batch: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, h.url, bytes.NewReader(data))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	if h.apiKey != "" {
		req.Header.Set("X-Collector-Key", h.apiKey)
	}

	resp, err := h.client.Do(req)
	if err != nil {
		return fmt.Errorf("http request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("http status: %d", resp.StatusCode)
	}

	return nil
}

// Close closes the HTTP sender.
func (h *HTTPSender) Close() error {
	h.client.CloseIdleConnections()
	return nil
}

// Name returns the sender name.
func (h *HTTPSender) Name() string {
	return "http"
}
