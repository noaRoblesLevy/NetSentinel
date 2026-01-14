package ipfix

import (
	"encoding/binary"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// buildIPFIXPacket creates a test IPFIX message with template and data.
func buildIPFIXPacket(t *testing.T) []byte {
	packet := make([]byte, 0, 512)
	exportTime := uint32(time.Now().Unix())

	// Message Header (16 bytes)
	header := make([]byte, 16)
	binary.BigEndian.PutUint16(header[0:2], 10)          // Version
	// Length will be filled at the end
	binary.BigEndian.PutUint32(header[4:8], exportTime)  // Export Time
	binary.BigEndian.PutUint32(header[8:12], 1)          // Sequence Number
	binary.BigEndian.PutUint32(header[12:16], 99999)     // Observation Domain ID
	packet = append(packet, header...)

	// Template Set (SetID = 2)
	templateSet := make([]byte, 4)
	binary.BigEndian.PutUint16(templateSet[0:2], 2)  // SetID (template)

	// Template Record: ID=256, 7 fields
	templateRecord := make([]byte, 0)
	templateHeader := make([]byte, 4)
	binary.BigEndian.PutUint16(templateHeader[0:2], 256)  // Template ID
	binary.BigEndian.PutUint16(templateHeader[2:4], 7)    // Field Count
	templateRecord = append(templateRecord, templateHeader...)

	// Fields
	fields := []struct {
		ID     uint16
		Length uint16
	}{
		{IESourceIPv4Address, 4},
		{IEDestinationIPv4Address, 4},
		{IESourceTransportPort, 2},
		{IEDestinationTransportPort, 2},
		{IEProtocolIdentifier, 1},
		{IEOctetDeltaCount, 4},
		{IEPacketDeltaCount, 4},
	}

	for _, f := range fields {
		fieldBytes := make([]byte, 4)
		binary.BigEndian.PutUint16(fieldBytes[0:2], f.ID)
		binary.BigEndian.PutUint16(fieldBytes[2:4], f.Length)
		templateRecord = append(templateRecord, fieldBytes...)
	}

	// Calculate template set length and pad
	templateSet = append(templateSet, templateRecord...)
	for len(templateSet)%4 != 0 {
		templateSet = append(templateSet, 0)
	}
	binary.BigEndian.PutUint16(templateSet[2:4], uint16(len(templateSet)))

	packet = append(packet, templateSet...)

	// Data Set (SetID = 256)
	dataSet := make([]byte, 4)
	binary.BigEndian.PutUint16(dataSet[0:2], 256)

	// Data Record (21 bytes: 4+4+2+2+1+4+4)
	dataRecord := make([]byte, 0, 21)

	// SourceIPv4Address: 10.0.0.50
	dataRecord = append(dataRecord, 10, 0, 0, 50)
	// DestinationIPv4Address: 172.16.0.1
	dataRecord = append(dataRecord, 172, 16, 0, 1)
	// SourceTransportPort: 54321
	srcPort := make([]byte, 2)
	binary.BigEndian.PutUint16(srcPort, 54321)
	dataRecord = append(dataRecord, srcPort...)
	// DestinationTransportPort: 8080
	dstPort := make([]byte, 2)
	binary.BigEndian.PutUint16(dstPort, 8080)
	dataRecord = append(dataRecord, dstPort...)
	// ProtocolIdentifier: 17 (UDP)
	dataRecord = append(dataRecord, 17)
	// OctetDeltaCount: 2048
	bytesField := make([]byte, 4)
	binary.BigEndian.PutUint32(bytesField, 2048)
	dataRecord = append(dataRecord, bytesField...)
	// PacketDeltaCount: 4
	packetsField := make([]byte, 4)
	binary.BigEndian.PutUint32(packetsField, 4)
	dataRecord = append(dataRecord, packetsField...)

	dataSet = append(dataSet, dataRecord...)

	// Pad data set
	for len(dataSet)%4 != 0 {
		dataSet = append(dataSet, 0)
	}
	binary.BigEndian.PutUint16(dataSet[2:4], uint16(len(dataSet)))

	packet = append(packet, dataSet...)

	// Update message length
	binary.BigEndian.PutUint16(packet[2:4], uint16(len(packet)))

	return packet
}

func TestIPFIXParser_Parse_ValidMessage(t *testing.T) {
	parser := NewParser()
	exporterIP := net.ParseIP("192.168.10.1")

	packet := buildIPFIXPacket(t)

	records, err := parser.Parse(packet, exporterIP)
	require.NoError(t, err)
	require.Len(t, records, 1)

	rec := records[0]
	assert.Equal(t, "10.0.0.50", rec.SrcIP.String())
	assert.Equal(t, "172.16.0.1", rec.DstIP.String())
	assert.Equal(t, uint16(54321), rec.SrcPort)
	assert.Equal(t, uint16(8080), rec.DstPort)
	assert.Equal(t, uint8(17), rec.Protocol) // UDP
	assert.Equal(t, uint64(2048), rec.Bytes)
	assert.Equal(t, uint64(4), rec.Packets)
	assert.Equal(t, "ipfix", rec.SourceFormat)
}

func TestIPFIXParser_Parse_InvalidVersion(t *testing.T) {
	parser := NewParser()
	exporterIP := net.ParseIP("192.168.10.1")

	// Create packet with wrong version
	packet := make([]byte, 16)
	binary.BigEndian.PutUint16(packet[0:2], 9) // Version 9 instead of 10
	binary.BigEndian.PutUint16(packet[2:4], 16)

	_, err := parser.Parse(packet, exporterIP)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "invalid IPFIX version")
}

func TestIPFIXParser_Parse_TooShort(t *testing.T) {
	parser := NewParser()
	exporterIP := net.ParseIP("192.168.10.1")

	// Packet too short for header
	packet := make([]byte, 10)

	_, err := parser.Parse(packet, exporterIP)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "too short")
}

func TestIPFIXParser_TemplateCache(t *testing.T) {
	parser := NewParser()
	exporterIP := net.ParseIP("192.168.10.1")

	packet := buildIPFIXPacket(t)
	_, err := parser.Parse(packet, exporterIP)
	require.NoError(t, err)

	assert.Equal(t, 1, parser.TemplateCount())
}

func TestIPFIXParser_Parse_NoTemplate(t *testing.T) {
	parser := NewParser()
	exporterIP := net.ParseIP("192.168.10.1")

	// Build data-only message without template
	packet := make([]byte, 0, 64)

	// Header
	header := make([]byte, 16)
	binary.BigEndian.PutUint16(header[0:2], 10)
	binary.BigEndian.PutUint32(header[4:8], uint32(time.Now().Unix()))
	binary.BigEndian.PutUint32(header[8:12], 1)
	binary.BigEndian.PutUint32(header[12:16], 99999)
	packet = append(packet, header...)

	// Data Set with unknown template ID
	dataSet := make([]byte, 8)
	binary.BigEndian.PutUint16(dataSet[0:2], 512)  // Unknown template
	binary.BigEndian.PutUint16(dataSet[2:4], 8)
	packet = append(packet, dataSet...)

	binary.BigEndian.PutUint16(packet[2:4], uint16(len(packet)))

	records, err := parser.Parse(packet, exporterIP)
	require.NoError(t, err)
	// Should return empty records since template not found
	assert.Len(t, records, 0)
}

func TestIPFIXParser_Parse_IPv6(t *testing.T) {
	parser := NewParser()
	exporterIP := net.ParseIP("192.168.10.1")

	packet := make([]byte, 0, 256)

	// Header
	header := make([]byte, 16)
	binary.BigEndian.PutUint16(header[0:2], 10)
	binary.BigEndian.PutUint32(header[4:8], uint32(time.Now().Unix()))
	binary.BigEndian.PutUint32(header[8:12], 1)
	binary.BigEndian.PutUint32(header[12:16], 88888)
	packet = append(packet, header...)

	// Template Set for IPv6
	templateSet := make([]byte, 4)
	binary.BigEndian.PutUint16(templateSet[0:2], 2)

	// Template ID=257 with IPv6 addresses
	templateRecord := make([]byte, 0)
	templateHeader := make([]byte, 4)
	binary.BigEndian.PutUint16(templateHeader[0:2], 257)
	binary.BigEndian.PutUint16(templateHeader[2:4], 5)
	templateRecord = append(templateRecord, templateHeader...)

	// IPv6 source (16), IPv6 dest (16), proto (1), bytes (4), packets (4)
	v6Fields := []struct {
		ID     uint16
		Length uint16
	}{
		{IESourceIPv6Address, 16},
		{IEDestinationIPv6Address, 16},
		{IEProtocolIdentifier, 1},
		{IEOctetDeltaCount, 4},
		{IEPacketDeltaCount, 4},
	}

	for _, f := range v6Fields {
		fieldBytes := make([]byte, 4)
		binary.BigEndian.PutUint16(fieldBytes[0:2], f.ID)
		binary.BigEndian.PutUint16(fieldBytes[2:4], f.Length)
		templateRecord = append(templateRecord, fieldBytes...)
	}

	templateSet = append(templateSet, templateRecord...)
	for len(templateSet)%4 != 0 {
		templateSet = append(templateSet, 0)
	}
	binary.BigEndian.PutUint16(templateSet[2:4], uint16(len(templateSet)))
	packet = append(packet, templateSet...)

	// Data Set
	dataSet := make([]byte, 4)
	binary.BigEndian.PutUint16(dataSet[0:2], 257)

	// IPv6 data record
	// Source: 2001:db8::1
	srcIPv6 := net.ParseIP("2001:db8::1")
	dataSet = append(dataSet, srcIPv6.To16()...)
	// Dest: 2001:db8::2
	dstIPv6 := net.ParseIP("2001:db8::2")
	dataSet = append(dataSet, dstIPv6.To16()...)
	// Protocol: 6 (TCP)
	dataSet = append(dataSet, 6)
	// Bytes: 5000
	bytesField := make([]byte, 4)
	binary.BigEndian.PutUint32(bytesField, 5000)
	dataSet = append(dataSet, bytesField...)
	// Packets: 50
	packetsField := make([]byte, 4)
	binary.BigEndian.PutUint32(packetsField, 50)
	dataSet = append(dataSet, packetsField...)

	for len(dataSet)%4 != 0 {
		dataSet = append(dataSet, 0)
	}
	binary.BigEndian.PutUint16(dataSet[2:4], uint16(len(dataSet)))
	packet = append(packet, dataSet...)

	binary.BigEndian.PutUint16(packet[2:4], uint16(len(packet)))

	records, err := parser.Parse(packet, exporterIP)
	require.NoError(t, err)
	require.Len(t, records, 1)

	rec := records[0]
	assert.Equal(t, "2001:db8::1", rec.SrcIP.String())
	assert.Equal(t, "2001:db8::2", rec.DstIP.String())
	assert.Equal(t, uint8(6), rec.Protocol)
	assert.Equal(t, uint64(5000), rec.Bytes)
	assert.Equal(t, uint64(50), rec.Packets)
}

func TestReadUintN_IPFIX(t *testing.T) {
	tests := []struct {
		name     string
		data     []byte
		expected uint64
	}{
		{"1 byte max", []byte{0xFF}, 255},
		{"2 bytes", []byte{0x12, 0x34}, 0x1234},
		{"3 bytes", []byte{0x12, 0x34, 0x56}, 0x123456},
		{"4 bytes", []byte{0x12, 0x34, 0x56, 0x78}, 0x12345678},
		{"8 bytes", []byte{0x00, 0x00, 0x00, 0x00, 0x12, 0x34, 0x56, 0x78}, 0x12345678},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := readUintN(tt.data)
			assert.Equal(t, tt.expected, result)
		})
	}
}
