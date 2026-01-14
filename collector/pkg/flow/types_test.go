package flow

import (
	"encoding/json"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRecord_MarshalJSON(t *testing.T) {
	rec := &Record{
		TimestampStart: time.Date(2024, 1, 15, 10, 30, 0, 0, time.UTC),
		TimestampEnd:   time.Date(2024, 1, 15, 10, 30, 5, 0, time.UTC),
		DurationMs:     5000,
		SrcIP:          net.ParseIP("192.168.1.100"),
		DstIP:          net.ParseIP("8.8.8.8"),
		SrcPort:        12345,
		DstPort:        443,
		Protocol:       6,
		Bytes:          1500,
		Packets:        10,
		TCPFlags:       0x18,
		ExporterIP:     net.ParseIP("10.0.0.1"),
		ExporterID:     "10.0.0.1:12345",
		SiteID:         "site-123",
		SourceFormat:   "netflow_v9",
	}

	data, err := json.Marshal(rec)
	require.NoError(t, err)

	// Parse back to verify
	var parsed map[string]interface{}
	err = json.Unmarshal(data, &parsed)
	require.NoError(t, err)

	assert.Equal(t, "192.168.1.100", parsed["src_ip"])
	assert.Equal(t, "8.8.8.8", parsed["dst_ip"])
	assert.Equal(t, "10.0.0.1", parsed["exporter_ip"])
	assert.Equal(t, float64(12345), parsed["src_port"])
	assert.Equal(t, float64(443), parsed["dst_port"])
	assert.Equal(t, float64(6), parsed["protocol"])
	assert.Equal(t, float64(1500), parsed["bytes"])
	assert.Equal(t, float64(10), parsed["packets"])
}

func TestRecord_MarshalJSON_IPv6(t *testing.T) {
	rec := &Record{
		TimestampStart: time.Now(),
		TimestampEnd:   time.Now(),
		SrcIP:          net.ParseIP("2001:db8::1"),
		DstIP:          net.ParseIP("2001:db8::2"),
		SrcPort:        54321,
		DstPort:        80,
		Protocol:       6,
		Bytes:          2048,
		Packets:        5,
		ExporterIP:     net.ParseIP("fe80::1"),
		ExporterID:     "fe80::1:99999",
		SourceFormat:   "ipfix",
	}

	data, err := json.Marshal(rec)
	require.NoError(t, err)

	var parsed map[string]interface{}
	err = json.Unmarshal(data, &parsed)
	require.NoError(t, err)

	assert.Equal(t, "2001:db8::1", parsed["src_ip"])
	assert.Equal(t, "2001:db8::2", parsed["dst_ip"])
	assert.Equal(t, "fe80::1", parsed["exporter_ip"])
}

func TestProtocolName(t *testing.T) {
	tests := []struct {
		proto    uint8
		expected string
	}{
		{1, "ICMP"},
		{6, "TCP"},
		{17, "UDP"},
		{47, "GRE"},
		{50, "ESP"},
		{51, "AH"},
		{58, "ICMPv6"},
		{89, "OSPF"},
		{99, "OTHER"},
		{0, "OTHER"},
	}

	for _, tt := range tests {
		t.Run(tt.expected, func(t *testing.T) {
			result := ProtocolName(tt.proto)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestTCPFlagsString(t *testing.T) {
	tests := []struct {
		flags    uint8
		expected string
	}{
		{0x00, "."},
		{0x01, "F"},
		{0x02, "S"},
		{0x03, "FS"},
		{0x10, "A"},
		{0x12, "SA"},
		{0x18, "PA"},
		{0x14, "RA"},
		{0x04, "R"},
		{0x3F, "FSRPAU"},
	}

	for _, tt := range tests {
		t.Run(tt.expected, func(t *testing.T) {
			result := TCPFlagsString(tt.flags)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestBatch_MarshalJSON(t *testing.T) {
	batch := &Batch{
		SiteID:     "site-abc",
		ExporterID: "10.0.0.1:12345",
		BatchID:    "batch-123",
		Timestamp:  time.Date(2024, 1, 15, 12, 0, 0, 0, time.UTC),
		Flows: []*Record{
			{
				SrcIP:    net.ParseIP("192.168.1.1"),
				DstIP:    net.ParseIP("8.8.8.8"),
				SrcPort:  12345,
				DstPort:  443,
				Protocol: 6,
				Bytes:    1000,
				Packets:  5,
			},
			{
				SrcIP:    net.ParseIP("192.168.1.2"),
				DstIP:    net.ParseIP("1.1.1.1"),
				SrcPort:  54321,
				DstPort:  53,
				Protocol: 17,
				Bytes:    100,
				Packets:  1,
			},
		},
	}

	data, err := json.Marshal(batch)
	require.NoError(t, err)

	var parsed map[string]interface{}
	err = json.Unmarshal(data, &parsed)
	require.NoError(t, err)

	assert.Equal(t, "site-abc", parsed["site_id"])
	assert.Equal(t, "10.0.0.1:12345", parsed["exporter_id"])
	assert.Equal(t, "batch-123", parsed["batch_id"])

	flows := parsed["flows"].([]interface{})
	assert.Len(t, flows, 2)
}
