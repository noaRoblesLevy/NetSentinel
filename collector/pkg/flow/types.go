// Package flow provides types and utilities for network flow records.
package flow

import (
	"encoding/json"
	"net"
	"time"
)

// Record represents a normalized flow record in canonical format.
// This is the common structure used regardless of the source format (NetFlow v5/v9/IPFIX).
type Record struct {
	// Timestamps
	TimestampStart time.Time `json:"ts_start"`
	TimestampEnd   time.Time `json:"ts_end"`
	DurationMs     int64     `json:"duration_ms"`

	// IP addresses
	SrcIP net.IP `json:"src_ip"`
	DstIP net.IP `json:"dst_ip"`

	// Ports
	SrcPort uint16 `json:"src_port"`
	DstPort uint16 `json:"dst_port"`

	// Protocol (6=TCP, 17=UDP, 1=ICMP, etc.)
	Protocol uint8 `json:"protocol"`

	// Traffic metrics
	Bytes   uint64 `json:"bytes"`
	Packets uint64 `json:"packets"`

	// TCP flags (if available)
	TCPFlags uint8 `json:"tcp_flags,omitempty"`

	// Exporter information
	ExporterIP net.IP `json:"exporter_ip"`
	ExporterID string `json:"exporter_id"`

	// Site identification (populated by collector)
	SiteID string `json:"site_id"`

	// Direction indicators (populated during enrichment)
	IsInternalSrc bool `json:"is_internal_src,omitempty"`
	IsInternalDst bool `json:"is_internal_dst,omitempty"`

	// Source format for debugging
	SourceFormat string `json:"source_format,omitempty"`
}

// MarshalJSON implements custom JSON marshaling for IP addresses.
func (r *Record) MarshalJSON() ([]byte, error) {
	type Alias Record
	return json.Marshal(&struct {
		*Alias
		SrcIP      string `json:"src_ip"`
		DstIP      string `json:"dst_ip"`
		ExporterIP string `json:"exporter_ip"`
	}{
		Alias:      (*Alias)(r),
		SrcIP:      r.SrcIP.String(),
		DstIP:      r.DstIP.String(),
		ExporterIP: r.ExporterIP.String(),
	})
}

// Batch represents a batch of flow records ready for sending.
type Batch struct {
	SiteID     string    `json:"site_id"`
	ExporterID string    `json:"exporter_id"`
	Flows      []*Record `json:"flows"`
	BatchID    string    `json:"batch_id,omitempty"`
	Timestamp  time.Time `json:"timestamp"`
}

// ProtocolName returns the human-readable protocol name.
func ProtocolName(proto uint8) string {
	switch proto {
	case 1:
		return "ICMP"
	case 6:
		return "TCP"
	case 17:
		return "UDP"
	case 47:
		return "GRE"
	case 50:
		return "ESP"
	case 51:
		return "AH"
	case 58:
		return "ICMPv6"
	case 89:
		return "OSPF"
	default:
		return "OTHER"
	}
}

// TCPFlagsString returns the TCP flags as a string representation.
func TCPFlagsString(flags uint8) string {
	var result string
	if flags&0x01 != 0 {
		result += "F" // FIN
	}
	if flags&0x02 != 0 {
		result += "S" // SYN
	}
	if flags&0x04 != 0 {
		result += "R" // RST
	}
	if flags&0x08 != 0 {
		result += "P" // PSH
	}
	if flags&0x10 != 0 {
		result += "A" // ACK
	}
	if flags&0x20 != 0 {
		result += "U" // URG
	}
	if result == "" {
		result = "."
	}
	return result
}
