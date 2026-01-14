// Package server provides the UDP server for receiving NetFlow/IPFIX packets.
package server

import (
	"net"
	"sync/atomic"
	"time"

	"github.com/netsentinel/collector/internal/config"
	"github.com/netsentinel/collector/internal/sender"
	"github.com/netsentinel/collector/pkg/flow"
	"github.com/netsentinel/collector/pkg/ipfix"
	"github.com/netsentinel/collector/pkg/netflow"
	log "github.com/sirupsen/logrus"
)

// UDPServer receives and processes NetFlow/IPFIX packets.
type UDPServer struct {
	cfg         *config.Config
	conn        *net.UDPConn
	batchSender *sender.BatchSender
	nfParser    *netflow.V9Parser
	ipfixParser *ipfix.Parser

	// Metrics
	packetsReceived atomic.Uint64
	packetsInvalid  atomic.Uint64
	bytesReceived   atomic.Uint64
	flowsParsed     atomic.Uint64
	parseErrors     atomic.Uint64

	// Control
	running atomic.Bool
}

// NewUDPServer creates a new UDP server.
func NewUDPServer(cfg *config.Config, batchSender *sender.BatchSender) *UDPServer {
	return &UDPServer{
		cfg:         cfg,
		batchSender: batchSender,
		nfParser:    netflow.NewV9Parser(),
		ipfixParser: ipfix.NewParser(),
	}
}

// Start begins listening for UDP packets.
func (s *UDPServer) Start() error {
	addr := &net.UDPAddr{
		Port: s.cfg.UDPPort,
		IP:   net.IPv4zero,
	}

	conn, err := net.ListenUDP("udp", addr)
	if err != nil {
		return err
	}

	// Set buffer size
	if err := conn.SetReadBuffer(s.cfg.UDPBufferSize); err != nil {
		log.WithError(err).Warn("Failed to set UDP read buffer size")
	}

	s.conn = conn
	s.running.Store(true)

	log.WithFields(log.Fields{
		"port":        s.cfg.UDPPort,
		"buffer_size": s.cfg.UDPBufferSize,
	}).Info("UDP server started")

	// Start packet processing loop
	go s.receiveLoop()

	return nil
}

// receiveLoop continuously receives and processes UDP packets.
func (s *UDPServer) receiveLoop() {
	buffer := make([]byte, s.cfg.UDPBufferSize)

	for s.running.Load() {
		// Set read deadline for graceful shutdown
		s.conn.SetReadDeadline(time.Now().Add(1 * time.Second))

		n, remoteAddr, err := s.conn.ReadFromUDP(buffer)
		if err != nil {
			if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
				continue // Normal timeout, check if still running
			}
			if !s.running.Load() {
				return // Server is stopping
			}
			log.WithError(err).Error("UDP read error")
			continue
		}

		s.packetsReceived.Add(1)
		s.bytesReceived.Add(uint64(n))

		// Make a copy of the data for processing
		data := make([]byte, n)
		copy(data, buffer[:n])

		// Process packet (could be done in goroutine for higher throughput)
		s.processPacket(data, remoteAddr.IP)
	}
}

// processPacket parses a NetFlow/IPFIX packet and submits flows for sending.
func (s *UDPServer) processPacket(data []byte, exporterIP net.IP) {
	if len(data) < 2 {
		s.packetsInvalid.Add(1)
		return
	}

	// Determine protocol version from first two bytes
	version := uint16(data[0])<<8 | uint16(data[1])

	var records []*flow.Record
	var err error

	switch version {
	case 9:
		// NetFlow v9
		records, err = s.nfParser.Parse(data, exporterIP)
	case 10:
		// IPFIX
		records, err = s.ipfixParser.Parse(data, exporterIP)
	default:
		s.packetsInvalid.Add(1)
		log.WithFields(log.Fields{
			"version":    version,
			"exporter":   exporterIP.String(),
			"packet_len": len(data),
		}).Debug("Unsupported protocol version")
		return
	}

	if err != nil {
		s.parseErrors.Add(1)
		log.WithFields(log.Fields{
			"error":    err,
			"exporter": exporterIP.String(),
			"version":  version,
		}).Debug("Parse error")
		return
	}

	// Submit parsed flows
	for _, rec := range records {
		// Set default site ID if not set
		if rec.SiteID == "" {
			rec.SiteID = s.cfg.DefaultSiteID
		}

		if !s.batchSender.Submit(rec) {
			// Backpressure - queue is full
			log.WithField("queue_depth", s.batchSender.QueueDepth()).Warn("Backpressure: queue full")
		}
	}

	s.flowsParsed.Add(uint64(len(records)))
}

// Stop gracefully shuts down the UDP server.
func (s *UDPServer) Stop() {
	log.Info("Stopping UDP server...")
	s.running.Store(false)
	if s.conn != nil {
		s.conn.Close()
	}
	log.Info("UDP server stopped")
}

// Stats returns current server metrics.
func (s *UDPServer) Stats() map[string]interface{} {
	return map[string]interface{}{
		"packets_received": s.packetsReceived.Load(),
		"packets_invalid":  s.packetsInvalid.Load(),
		"bytes_received":   s.bytesReceived.Load(),
		"flows_parsed":     s.flowsParsed.Load(),
		"parse_errors":     s.parseErrors.Load(),
		"nf_templates":     s.nfParser.TemplateCount(),
		"ipfix_templates":  s.ipfixParser.TemplateCount(),
	}
}

// IsRunning returns whether the server is currently running.
func (s *UDPServer) IsRunning() bool {
	return s.running.Load()
}
