// Package ipfix provides a parser for IPFIX (IP Flow Information Export) protocol.
// IPFIX is defined in RFC 7011 and is based on NetFlow v9.
package ipfix

import (
	"encoding/binary"
	"fmt"
	"net"
	"sync"
	"time"

	"github.com/netsentinel/collector/pkg/flow"
)

// IPFIX Information Element IDs (based on IANA registry)
// Most are compatible with NetFlow v9 field types
const (
	IEOctetDeltaCount        = 1
	IEPacketDeltaCount       = 2
	IEProtocolIdentifier     = 4
	IEIPClassOfService       = 5
	IETCPControlBits         = 6
	IESourceTransportPort    = 7
	IESourceIPv4Address      = 8
	IESourceIPv4PrefixLen    = 9
	IEIngressInterface       = 10
	IEDestinationTransportPort = 11
	IEDestinationIPv4Address = 12
	IEDestinationIPv4PrefixLen = 13
	IEEgressInterface        = 14
	IEIPNextHopIPv4Address   = 15
	IEBGPSourceAsNumber      = 16
	IEBGPDestinationAsNumber = 17
	IEFlowEndSysUpTime       = 21
	IEFlowStartSysUpTime     = 22
	IEPostOctetDeltaCount    = 23
	IEPostPacketDeltaCount   = 24
	IESourceIPv6Address      = 27
	IEDestinationIPv6Address = 28
	IESourceIPv6PrefixLen    = 29
	IEDestinationIPv6PrefixLen = 30
	IEFlowLabelIPv6          = 31
	IEIcmpTypeCodeIPv4       = 32
	IEFlowDirection          = 61
	IEFlowStartMilliseconds  = 152
	IEFlowEndMilliseconds    = 153
	IEFlowStartMicroseconds  = 154
	IEFlowEndMicroseconds    = 155
	IEFlowStartNanoseconds   = 156
	IEFlowEndNanoseconds     = 157
	IEFlowStartDeltaMicroseconds = 158
	IEFlowEndDeltaMicroseconds = 159
	IEObservationDomainId    = 149
)

// IPFIXHeader represents the IPFIX message header (RFC 7011).
type IPFIXHeader struct {
	Version         uint16
	Length          uint16
	ExportTime      uint32
	SequenceNumber  uint32
	ObservationDomainID uint32
}

// SetHeader represents an IPFIX Set header.
type SetHeader struct {
	SetID  uint16
	Length uint16
}

// TemplateField represents a field in a template record.
type TemplateField struct {
	InformationElementID uint16
	FieldLength         uint16
	EnterpriseNumber    uint32 // Present if IE ID has enterprise bit set
	IsEnterprise        bool
}

// Template represents a complete template record.
type Template struct {
	TemplateID uint16
	FieldCount uint16
	Fields     []TemplateField
	TotalLen   int
}

// Parser parses IPFIX messages.
type Parser struct {
	// Template cache: map[observationDomainID]map[templateID]template
	templates   map[uint32]map[uint16]*Template
	templatesMu sync.RWMutex
}

// NewParser creates a new IPFIX parser.
func NewParser() *Parser {
	return &Parser{
		templates: make(map[uint32]map[uint16]*Template),
	}
}

// Parse parses an IPFIX message and returns normalized flow records.
func (p *Parser) Parse(data []byte, exporterIP net.IP) ([]*flow.Record, error) {
	if len(data) < 16 {
		return nil, fmt.Errorf("packet too short for IPFIX header: %d bytes", len(data))
	}

	// Parse header
	header := IPFIXHeader{
		Version:             binary.BigEndian.Uint16(data[0:2]),
		Length:              binary.BigEndian.Uint16(data[2:4]),
		ExportTime:          binary.BigEndian.Uint32(data[4:8]),
		SequenceNumber:      binary.BigEndian.Uint32(data[8:12]),
		ObservationDomainID: binary.BigEndian.Uint32(data[12:16]),
	}

	if header.Version != 10 {
		return nil, fmt.Errorf("invalid IPFIX version: expected 10, got %d", header.Version)
	}

	if int(header.Length) > len(data) {
		return nil, fmt.Errorf("declared length %d exceeds data length %d", header.Length, len(data))
	}

	exportTime := time.Unix(int64(header.ExportTime), 0)
	records := make([]*flow.Record, 0)

	offset := 16
	for offset < int(header.Length) {
		if offset+4 > len(data) {
			break
		}

		setHeader := SetHeader{
			SetID:  binary.BigEndian.Uint16(data[offset : offset+2]),
			Length: binary.BigEndian.Uint16(data[offset+2 : offset+4]),
		}

		if setHeader.Length < 4 {
			break // Invalid length
		}

		if offset+int(setHeader.Length) > len(data) {
			break // Incomplete Set
		}

		setData := data[offset+4 : offset+int(setHeader.Length)]

		switch {
		case setHeader.SetID == 2:
			// Template Set
			p.parseTemplateSet(setData, header.ObservationDomainID)

		case setHeader.SetID == 3:
			// Options Template Set (skip for now)

		case setHeader.SetID >= 256:
			// Data Set
			recs := p.parseDataSet(setData, setHeader.SetID, header.ObservationDomainID, exportTime, exporterIP)
			records = append(records, recs...)
		}

		offset += int(setHeader.Length)
	}

	return records, nil
}

// parseTemplateSet parses template records from a template Set.
func (p *Parser) parseTemplateSet(data []byte, observationDomainID uint32) {
	offset := 0

	for offset+4 <= len(data) {
		templateID := binary.BigEndian.Uint16(data[offset : offset+2])
		fieldCount := binary.BigEndian.Uint16(data[offset+2 : offset+4])
		offset += 4

		if fieldCount == 0 || templateID < 256 {
			continue
		}

		template := &Template{
			TemplateID: templateID,
			FieldCount: fieldCount,
			Fields:     make([]TemplateField, 0, fieldCount),
			TotalLen:   0,
		}

		for i := uint16(0); i < fieldCount && offset+4 <= len(data); i++ {
			ieID := binary.BigEndian.Uint16(data[offset : offset+2])
			fieldLen := binary.BigEndian.Uint16(data[offset+2 : offset+4])
			offset += 4

			field := TemplateField{
				InformationElementID: ieID & 0x7FFF, // Mask out enterprise bit
				FieldLength:         fieldLen,
				IsEnterprise:        ieID&0x8000 != 0,
			}

			// If enterprise bit is set, read enterprise number
			if field.IsEnterprise && offset+4 <= len(data) {
				field.EnterpriseNumber = binary.BigEndian.Uint32(data[offset : offset+4])
				offset += 4
			}

			// Handle variable-length fields
			if fieldLen == 65535 {
				// Variable length - will be determined at data record time
				// For now, skip contribution to TotalLen
			} else {
				template.TotalLen += int(fieldLen)
			}

			template.Fields = append(template.Fields, field)
		}

		// Store template
		p.templatesMu.Lock()
		if p.templates[observationDomainID] == nil {
			p.templates[observationDomainID] = make(map[uint16]*Template)
		}
		p.templates[observationDomainID][templateID] = template
		p.templatesMu.Unlock()
	}
}

// parseDataSet parses data records using a previously received template.
func (p *Parser) parseDataSet(data []byte, templateID uint16, observationDomainID uint32, exportTime time.Time, exporterIP net.IP) []*flow.Record {
	p.templatesMu.RLock()
	domainTemplates := p.templates[observationDomainID]
	if domainTemplates == nil {
		p.templatesMu.RUnlock()
		return nil
	}
	template := domainTemplates[templateID]
	p.templatesMu.RUnlock()

	if template == nil || len(template.Fields) == 0 {
		return nil
	}

	records := make([]*flow.Record, 0)
	offset := 0

	for offset < len(data) {
		rec := &flow.Record{
			ExporterIP:   exporterIP,
			ExporterID:   fmt.Sprintf("%s:%d", exporterIP.String(), observationDomainID),
			SourceFormat: "ipfix",
			TimestampEnd: exportTime, // Default to export time
		}

		recordStart := offset
		for _, field := range template.Fields {
			fieldLen := int(field.FieldLength)

			// Handle variable-length fields
			if field.FieldLength == 65535 {
				if offset >= len(data) {
					break
				}
				// Read length prefix
				if data[offset] < 255 {
					fieldLen = int(data[offset])
					offset++
				} else if offset+3 <= len(data) {
					fieldLen = int(binary.BigEndian.Uint16(data[offset+1 : offset+3]))
					offset += 3
				} else {
					break
				}
			}

			if offset+fieldLen > len(data) {
				break
			}

			// Skip enterprise-specific fields
			if !field.IsEnterprise {
				fieldData := data[offset : offset+fieldLen]
				p.extractField(rec, field.InformationElementID, fieldData, exportTime)
			}
			offset += fieldLen
		}

		// Skip if no progress was made (template issue)
		if offset == recordStart {
			break
		}

		// Calculate duration
		if !rec.TimestampStart.IsZero() && !rec.TimestampEnd.IsZero() {
			rec.DurationMs = rec.TimestampEnd.Sub(rec.TimestampStart).Milliseconds()
		}

		// Set defaults if timestamps are missing
		if rec.TimestampStart.IsZero() {
			rec.TimestampStart = exportTime
		}

		records = append(records, rec)
	}

	return records
}

// extractField extracts a field value and populates the flow record.
func (p *Parser) extractField(rec *flow.Record, ieID uint16, data []byte, exportTime time.Time) {
	switch ieID {
	case IESourceIPv4Address:
		if len(data) >= 4 {
			rec.SrcIP = net.IP(data[:4])
		}
	case IEDestinationIPv4Address:
		if len(data) >= 4 {
			rec.DstIP = net.IP(data[:4])
		}
	case IESourceIPv6Address:
		if len(data) >= 16 {
			rec.SrcIP = net.IP(data[:16])
		}
	case IEDestinationIPv6Address:
		if len(data) >= 16 {
			rec.DstIP = net.IP(data[:16])
		}
	case IESourceTransportPort:
		if len(data) >= 2 {
			rec.SrcPort = binary.BigEndian.Uint16(data)
		}
	case IEDestinationTransportPort:
		if len(data) >= 2 {
			rec.DstPort = binary.BigEndian.Uint16(data)
		}
	case IEProtocolIdentifier:
		if len(data) >= 1 {
			rec.Protocol = data[0]
		}
	case IEOctetDeltaCount, IEPostOctetDeltaCount:
		rec.Bytes += readUintN(data)
	case IEPacketDeltaCount, IEPostPacketDeltaCount:
		rec.Packets += readUintN(data)
	case IETCPControlBits:
		if len(data) >= 1 {
			rec.TCPFlags = data[len(data)-1] // Take last byte for flags
		}
	case IEFlowStartMilliseconds:
		if len(data) >= 8 {
			ms := binary.BigEndian.Uint64(data)
			rec.TimestampStart = time.UnixMilli(int64(ms))
		}
	case IEFlowEndMilliseconds:
		if len(data) >= 8 {
			ms := binary.BigEndian.Uint64(data)
			rec.TimestampEnd = time.UnixMilli(int64(ms))
		}
	case IEFlowStartSysUpTime:
		if len(data) >= 4 {
			// Relative to export time - approximate
			uptime := binary.BigEndian.Uint32(data)
			rec.TimestampStart = exportTime.Add(-time.Duration(uptime) * time.Millisecond)
		}
	case IEFlowEndSysUpTime:
		if len(data) >= 4 {
			uptime := binary.BigEndian.Uint32(data)
			rec.TimestampEnd = exportTime.Add(-time.Duration(uptime) * time.Millisecond)
		}
	}
}

// readUintN reads an unsigned integer of variable length.
func readUintN(data []byte) uint64 {
	switch len(data) {
	case 1:
		return uint64(data[0])
	case 2:
		return uint64(binary.BigEndian.Uint16(data))
	case 4:
		return uint64(binary.BigEndian.Uint32(data))
	case 8:
		return binary.BigEndian.Uint64(data)
	default:
		// Handle other lengths
		var result uint64
		for _, b := range data {
			result = (result << 8) | uint64(b)
		}
		return result
	}
}

// TemplateCount returns the number of cached templates.
func (p *Parser) TemplateCount() int {
	p.templatesMu.RLock()
	defer p.templatesMu.RUnlock()

	count := 0
	for _, domainTemplates := range p.templates {
		count += len(domainTemplates)
	}
	return count
}
