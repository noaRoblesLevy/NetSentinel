package netflow

import (
	"encoding/binary"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// buildNetFlowV9Packet creates a test NetFlow v9 packet with template and data.
func buildNetFlowV9Packet(t *testing.T) []byte {
	packet := make([]byte, 0, 512)

	// Header (20 bytes)
	header := make([]byte, 20)
	binary.BigEndian.PutUint16(header[0:2], 9)           // Version
	binary.BigEndian.PutUint16(header[2:4], 2)           // Count (2 FlowSets)
	binary.BigEndian.PutUint32(header[4:8], 1000000)     // SysUptime (ms)
	binary.BigEndian.PutUint32(header[8:12], uint32(time.Now().Unix())) // UnixSecs
	binary.BigEndian.PutUint32(header[12:16], 1)         // Sequence
	binary.BigEndian.PutUint32(header[16:20], 12345)     // SourceID
	packet = append(packet, header...)

	// Template FlowSet (FlowSetID = 0)
	// Template: ID=256, 8 fields
	templateFlowSet := make([]byte, 0, 48)
	binary.BigEndian.PutUint16(templateFlowSet[0:2], 0)  // FlowSetID (template)
	// Length will be filled later

	// Template Record
	templateRecord := make([]byte, 0)
	templateID := make([]byte, 4)
	binary.BigEndian.PutUint16(templateID[0:2], 256)     // Template ID
	binary.BigEndian.PutUint16(templateID[2:4], 8)       // Field Count
	templateRecord = append(templateRecord, templateID...)

	// Fields: SrcIP(4), DstIP(4), SrcPort(2), DstPort(2), Protocol(1), Bytes(4), Packets(4), TCPFlags(1)
	fields := []struct {
		Type   uint16
		Length uint16
	}{
		{NFv9FieldIPv4SrcAddr, 4},
		{NFv9FieldIPv4DstAddr, 4},
		{NFv9FieldL4SrcPort, 2},
		{NFv9FieldL4DstPort, 2},
		{NFv9FieldProtocol, 1},
		{NFv9FieldInBytes, 4},
		{NFv9FieldInPkts, 4},
		{NFv9FieldTCPFlags, 1},
	}

	for _, f := range fields {
		fieldBytes := make([]byte, 4)
		binary.BigEndian.PutUint16(fieldBytes[0:2], f.Type)
		binary.BigEndian.PutUint16(fieldBytes[2:4], f.Length)
		templateRecord = append(templateRecord, fieldBytes...)
	}

	// Build template FlowSet
	templateFlowSet = make([]byte, 4)
	binary.BigEndian.PutUint16(templateFlowSet[0:2], 0)                                    // FlowSetID
	binary.BigEndian.PutUint16(templateFlowSet[2:4], uint16(4+len(templateRecord)))       // Length
	templateFlowSet = append(templateFlowSet, templateRecord...)

	// Pad to 4-byte boundary
	for len(templateFlowSet)%4 != 0 {
		templateFlowSet = append(templateFlowSet, 0)
	}
	// Update length
	binary.BigEndian.PutUint16(templateFlowSet[2:4], uint16(len(templateFlowSet)))

	packet = append(packet, templateFlowSet...)

	// Data FlowSet (FlowSetID = 256)
	dataFlowSet := make([]byte, 4)
	binary.BigEndian.PutUint16(dataFlowSet[0:2], 256)  // FlowSetID (matches template)

	// Data Record (22 bytes: 4+4+2+2+1+4+4+1)
	dataRecord := make([]byte, 0, 22)

	// SrcIP: 192.168.1.100
	dataRecord = append(dataRecord, 192, 168, 1, 100)
	// DstIP: 8.8.8.8
	dataRecord = append(dataRecord, 8, 8, 8, 8)
	// SrcPort: 12345
	srcPort := make([]byte, 2)
	binary.BigEndian.PutUint16(srcPort, 12345)
	dataRecord = append(dataRecord, srcPort...)
	// DstPort: 443
	dstPort := make([]byte, 2)
	binary.BigEndian.PutUint16(dstPort, 443)
	dataRecord = append(dataRecord, dstPort...)
	// Protocol: 6 (TCP)
	dataRecord = append(dataRecord, 6)
	// Bytes: 1500
	bytesField := make([]byte, 4)
	binary.BigEndian.PutUint32(bytesField, 1500)
	dataRecord = append(dataRecord, bytesField...)
	// Packets: 10
	packetsField := make([]byte, 4)
	binary.BigEndian.PutUint32(packetsField, 10)
	dataRecord = append(dataRecord, packetsField...)
	// TCPFlags: 0x18 (ACK+PSH)
	dataRecord = append(dataRecord, 0x18)

	// Add data FlowSet length
	binary.BigEndian.PutUint16(dataFlowSet[2:4], uint16(4+len(dataRecord)))
	dataFlowSet = append(dataFlowSet, dataRecord...)

	// Pad to 4-byte boundary
	for len(dataFlowSet)%4 != 0 {
		dataFlowSet = append(dataFlowSet, 0)
	}
	// Update length
	binary.BigEndian.PutUint16(dataFlowSet[2:4], uint16(len(dataFlowSet)))

	packet = append(packet, dataFlowSet...)

	return packet
}

func TestV9Parser_Parse_ValidPacket(t *testing.T) {
	parser := NewV9Parser()
	exporterIP := net.ParseIP("10.0.0.1")

	packet := buildNetFlowV9Packet(t)

	records, err := parser.Parse(packet, exporterIP)
	require.NoError(t, err)
	require.Len(t, records, 1)

	rec := records[0]
	assert.Equal(t, "192.168.1.100", rec.SrcIP.String())
	assert.Equal(t, "8.8.8.8", rec.DstIP.String())
	assert.Equal(t, uint16(12345), rec.SrcPort)
	assert.Equal(t, uint16(443), rec.DstPort)
	assert.Equal(t, uint8(6), rec.Protocol)
	assert.Equal(t, uint64(1500), rec.Bytes)
	assert.Equal(t, uint64(10), rec.Packets)
	assert.Equal(t, uint8(0x18), rec.TCPFlags)
	assert.Equal(t, "netflow_v9", rec.SourceFormat)
	assert.Equal(t, exporterIP.String(), rec.ExporterIP.String())
}

func TestV9Parser_Parse_InvalidVersion(t *testing.T) {
	parser := NewV9Parser()
	exporterIP := net.ParseIP("10.0.0.1")

	// Create packet with wrong version
	packet := make([]byte, 20)
	binary.BigEndian.PutUint16(packet[0:2], 5) // Version 5 instead of 9

	_, err := parser.Parse(packet, exporterIP)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "invalid NetFlow version")
}

func TestV9Parser_Parse_TooShort(t *testing.T) {
	parser := NewV9Parser()
	exporterIP := net.ParseIP("10.0.0.1")

	// Packet too short for header
	packet := make([]byte, 10)

	_, err := parser.Parse(packet, exporterIP)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "too short")
}

func TestV9Parser_TemplateCache(t *testing.T) {
	parser := NewV9Parser()
	exporterIP := net.ParseIP("10.0.0.1")

	// First parse to register template
	packet := buildNetFlowV9Packet(t)
	_, err := parser.Parse(packet, exporterIP)
	require.NoError(t, err)

	// Check template was cached
	assert.Equal(t, 1, parser.TemplateCount())
}

func TestV9Parser_Parse_MultipleRecords(t *testing.T) {
	parser := NewV9Parser()
	exporterIP := net.ParseIP("10.0.0.1")

	// First, send template
	packet := buildNetFlowV9Packet(t)
	_, err := parser.Parse(packet, exporterIP)
	require.NoError(t, err)

	// Now build a data-only packet with multiple records
	dataPacket := make([]byte, 0, 256)

	// Header
	header := make([]byte, 20)
	binary.BigEndian.PutUint16(header[0:2], 9)           // Version
	binary.BigEndian.PutUint16(header[2:4], 1)           // Count
	binary.BigEndian.PutUint32(header[4:8], 2000000)     // SysUptime
	binary.BigEndian.PutUint32(header[8:12], uint32(time.Now().Unix()))
	binary.BigEndian.PutUint32(header[12:16], 2)         // Sequence
	binary.BigEndian.PutUint32(header[16:20], 12345)     // SourceID
	dataPacket = append(dataPacket, header...)

	// Data FlowSet with 2 records
	dataFlowSet := make([]byte, 4)
	binary.BigEndian.PutUint16(dataFlowSet[0:2], 256)

	// Record 1
	record1 := []byte{
		192, 168, 1, 10,    // SrcIP
		1, 1, 1, 1,         // DstIP
		0x30, 0x39,         // SrcPort: 12345
		0x00, 0x50,         // DstPort: 80
		6,                  // Protocol: TCP
		0, 0, 0x05, 0xDC,   // Bytes: 1500
		0, 0, 0, 5,         // Packets: 5
		0x02,               // TCPFlags: SYN
	}

	// Record 2
	record2 := []byte{
		192, 168, 1, 20,    // SrcIP
		8, 8, 4, 4,         // DstIP
		0xC0, 0x00,         // SrcPort: 49152
		0x01, 0xBB,         // DstPort: 443
		6,                  // Protocol: TCP
		0, 0, 0x0B, 0xB8,   // Bytes: 3000
		0, 0, 0, 20,        // Packets: 20
		0x10,               // TCPFlags: ACK
	}

	dataFlowSet = append(dataFlowSet, record1...)
	dataFlowSet = append(dataFlowSet, record2...)

	// Pad and set length
	for len(dataFlowSet)%4 != 0 {
		dataFlowSet = append(dataFlowSet, 0)
	}
	binary.BigEndian.PutUint16(dataFlowSet[2:4], uint16(len(dataFlowSet)))

	dataPacket = append(dataPacket, dataFlowSet...)

	records, err := parser.Parse(dataPacket, exporterIP)
	require.NoError(t, err)
	require.Len(t, records, 2)

	// Verify first record
	assert.Equal(t, "192.168.1.10", records[0].SrcIP.String())
	assert.Equal(t, uint16(80), records[0].DstPort)
	assert.Equal(t, uint64(5), records[0].Packets)

	// Verify second record
	assert.Equal(t, "192.168.1.20", records[1].SrcIP.String())
	assert.Equal(t, uint16(443), records[1].DstPort)
	assert.Equal(t, uint64(20), records[1].Packets)
}

func TestReadUintN(t *testing.T) {
	tests := []struct {
		name     string
		data     []byte
		expected uint64
	}{
		{"1 byte", []byte{0xFF}, 255},
		{"2 bytes", []byte{0x01, 0x00}, 256},
		{"4 bytes", []byte{0x00, 0x01, 0x00, 0x00}, 65536},
		{"8 bytes", []byte{0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00}, 4294967296},
		{"empty", []byte{}, 0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := readUintN(tt.data)
			assert.Equal(t, tt.expected, result)
		})
	}
}
