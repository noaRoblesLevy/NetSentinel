// Package netflow provides parsers for NetFlow v5 and v9 formats.
package netflow

import (
	"encoding/binary"
	"fmt"
	"net"
	"sync"
	"time"

	"github.com/netsentinel/collector/pkg/flow"
)

// NetFlow v9 field type IDs (RFC 3954)
const (
	NFv9FieldInBytes         = 1
	NFv9FieldInPkts          = 2
	NFv9FieldFlows           = 3
	NFv9FieldProtocol        = 4
	NFv9FieldSrcTos          = 5
	NFv9FieldTCPFlags        = 6
	NFv9FieldL4SrcPort       = 7
	NFv9FieldIPv4SrcAddr     = 8
	NFv9FieldSrcMask         = 9
	NFv9FieldInputSnmp       = 10
	NFv9FieldL4DstPort       = 11
	NFv9FieldIPv4DstAddr     = 12
	NFv9FieldDstMask         = 13
	NFv9FieldOutputSnmp      = 14
	NFv9FieldIPv4NextHop     = 15
	NFv9FieldSrcAS           = 16
	NFv9FieldDstAS           = 17
	NFv9FieldLastSwitched    = 21
	NFv9FieldFirstSwitched   = 22
	NFv9FieldOutBytes        = 23
	NFv9FieldOutPkts         = 24
	NFv9FieldIPv6SrcAddr     = 27
	NFv9FieldIPv6DstAddr     = 28
	NFv9FieldIPv6FlowLabel   = 31
	NFv9FieldICMPType        = 32
	NFv9FieldDirection       = 61
	NFv9FieldIPv6OptionHdrs  = 64
	NFv9FieldFlowSamplerID   = 48
	NFv9FieldFlowActiveTO    = 36
	NFv9FieldFlowInactiveTO  = 37
)

// V9Header represents the NetFlow v9 packet header.
type V9Header struct {
	Version        uint16
	Count          uint16
	SysUptime      uint32
	UnixSecs       uint32
	SequenceNumber uint32
	SourceID       uint32
}

// V9FlowSetHeader represents a FlowSet header (template or data).
type V9FlowSetHeader struct {
	FlowSetID uint16
	Length    uint16
}

// V9TemplateField represents a field in a template.
type V9TemplateField struct {
	Type   uint16
	Length uint16
}

// V9Template represents a complete template definition.
type V9Template struct {
	TemplateID uint16
	FieldCount uint16
	Fields     []V9TemplateField
	TotalLen   int
}

// V9Parser parses NetFlow v9 packets.
type V9Parser struct {
	// Template cache: map[sourceID]map[templateID]template
	templates   map[uint32]map[uint16]*V9Template
	templatesMu sync.RWMutex
}

// NewV9Parser creates a new NetFlow v9 parser.
func NewV9Parser() *V9Parser {
	return &V9Parser{
		templates: make(map[uint32]map[uint16]*V9Template),
	}
}

// Parse parses a NetFlow v9 packet and returns normalized flow records.
func (p *V9Parser) Parse(data []byte, exporterIP net.IP) ([]*flow.Record, error) {
	if len(data) < 20 {
		return nil, fmt.Errorf("packet too short for NetFlow v9 header: %d bytes", len(data))
	}

	// Parse header
	header := V9Header{
		Version:        binary.BigEndian.Uint16(data[0:2]),
		Count:          binary.BigEndian.Uint16(data[2:4]),
		SysUptime:      binary.BigEndian.Uint32(data[4:8]),
		UnixSecs:       binary.BigEndian.Uint32(data[8:12]),
		SequenceNumber: binary.BigEndian.Uint32(data[12:16]),
		SourceID:       binary.BigEndian.Uint32(data[16:20]),
	}

	if header.Version != 9 {
		return nil, fmt.Errorf("invalid NetFlow version: expected 9, got %d", header.Version)
	}

	baseTime := time.Unix(int64(header.UnixSecs), 0)
	records := make([]*flow.Record, 0)

	offset := 20
	for offset < len(data) {
		if offset+4 > len(data) {
			break
		}

		fsHeader := V9FlowSetHeader{
			FlowSetID: binary.BigEndian.Uint16(data[offset : offset+2]),
			Length:    binary.BigEndian.Uint16(data[offset+2 : offset+4]),
		}

		if fsHeader.Length < 4 {
			break // Invalid length
		}

		if offset+int(fsHeader.Length) > len(data) {
			break // Incomplete FlowSet
		}

		flowSetData := data[offset+4 : offset+int(fsHeader.Length)]

		switch {
		case fsHeader.FlowSetID == 0:
			// Template FlowSet
			p.parseTemplateFlowSet(flowSetData, header.SourceID)

		case fsHeader.FlowSetID == 1:
			// Options Template FlowSet (skip for now)

		case fsHeader.FlowSetID >= 256:
			// Data FlowSet
			recs := p.parseDataFlowSet(flowSetData, fsHeader.FlowSetID, header.SourceID, baseTime, header.SysUptime, exporterIP)
			records = append(records, recs...)
		}

		offset += int(fsHeader.Length)
		// Align to 4-byte boundary
		if offset%4 != 0 {
			offset += 4 - (offset % 4)
		}
	}

	return records, nil
}

// parseTemplateFlowSet parses template definitions from a template FlowSet.
func (p *V9Parser) parseTemplateFlowSet(data []byte, sourceID uint32) {
	offset := 0

	for offset+4 <= len(data) {
		templateID := binary.BigEndian.Uint16(data[offset : offset+2])
		fieldCount := binary.BigEndian.Uint16(data[offset+2 : offset+4])
		offset += 4

		if fieldCount == 0 {
			continue
		}

		template := &V9Template{
			TemplateID: templateID,
			FieldCount: fieldCount,
			Fields:     make([]V9TemplateField, fieldCount),
			TotalLen:   0,
		}

		for i := uint16(0); i < fieldCount && offset+4 <= len(data); i++ {
			template.Fields[i] = V9TemplateField{
				Type:   binary.BigEndian.Uint16(data[offset : offset+2]),
				Length: binary.BigEndian.Uint16(data[offset+2 : offset+4]),
			}
			template.TotalLen += int(template.Fields[i].Length)
			offset += 4
		}

		// Store template
		p.templatesMu.Lock()
		if p.templates[sourceID] == nil {
			p.templates[sourceID] = make(map[uint16]*V9Template)
		}
		p.templates[sourceID][templateID] = template
		p.templatesMu.Unlock()
	}
}

// parseDataFlowSet parses data records using a previously received template.
func (p *V9Parser) parseDataFlowSet(data []byte, templateID uint16, sourceID uint32, baseTime time.Time, sysUptime uint32, exporterIP net.IP) []*flow.Record {
	p.templatesMu.RLock()
	sourceTemplates := p.templates[sourceID]
	if sourceTemplates == nil {
		p.templatesMu.RUnlock()
		return nil
	}
	template := sourceTemplates[templateID]
	p.templatesMu.RUnlock()

	if template == nil || template.TotalLen == 0 {
		return nil
	}

	records := make([]*flow.Record, 0)
	offset := 0

	for offset+template.TotalLen <= len(data) {
		rec := &flow.Record{
			ExporterIP:   exporterIP,
			ExporterID:   fmt.Sprintf("%s:%d", exporterIP.String(), sourceID),
			SourceFormat: "netflow_v9",
		}

		fieldOffset := offset
		for _, field := range template.Fields {
			if fieldOffset+int(field.Length) > len(data) {
				break
			}
			fieldData := data[fieldOffset : fieldOffset+int(field.Length)]
			p.extractField(rec, field.Type, fieldData, baseTime, sysUptime)
			fieldOffset += int(field.Length)
		}

		// Calculate duration
		if !rec.TimestampStart.IsZero() && !rec.TimestampEnd.IsZero() {
			rec.DurationMs = rec.TimestampEnd.Sub(rec.TimestampStart).Milliseconds()
		}

		// Set defaults if timestamps are missing
		if rec.TimestampStart.IsZero() {
			rec.TimestampStart = baseTime
		}
		if rec.TimestampEnd.IsZero() {
			rec.TimestampEnd = baseTime
		}

		records = append(records, rec)
		offset += template.TotalLen
	}

	return records
}

// extractField extracts a field value and populates the flow record.
func (p *V9Parser) extractField(rec *flow.Record, fieldType uint16, data []byte, baseTime time.Time, sysUptime uint32) {
	switch fieldType {
	case NFv9FieldIPv4SrcAddr:
		if len(data) >= 4 {
			rec.SrcIP = net.IP(data[:4])
		}
	case NFv9FieldIPv4DstAddr:
		if len(data) >= 4 {
			rec.DstIP = net.IP(data[:4])
		}
	case NFv9FieldIPv6SrcAddr:
		if len(data) >= 16 {
			rec.SrcIP = net.IP(data[:16])
		}
	case NFv9FieldIPv6DstAddr:
		if len(data) >= 16 {
			rec.DstIP = net.IP(data[:16])
		}
	case NFv9FieldL4SrcPort:
		if len(data) >= 2 {
			rec.SrcPort = binary.BigEndian.Uint16(data)
		}
	case NFv9FieldL4DstPort:
		if len(data) >= 2 {
			rec.DstPort = binary.BigEndian.Uint16(data)
		}
	case NFv9FieldProtocol:
		if len(data) >= 1 {
			rec.Protocol = data[0]
		}
	case NFv9FieldInBytes:
		rec.Bytes = readUintN(data)
	case NFv9FieldOutBytes:
		rec.Bytes += readUintN(data)
	case NFv9FieldInPkts:
		rec.Packets = readUintN(data)
	case NFv9FieldOutPkts:
		rec.Packets += readUintN(data)
	case NFv9FieldTCPFlags:
		if len(data) >= 1 {
			rec.TCPFlags = data[0]
		}
	case NFv9FieldFirstSwitched:
		if len(data) >= 4 {
			firstMs := binary.BigEndian.Uint32(data)
			// FirstSwitched is relative to system boot time
			deltaMs := int64(sysUptime) - int64(firstMs)
			rec.TimestampStart = baseTime.Add(-time.Duration(deltaMs) * time.Millisecond)
		}
	case NFv9FieldLastSwitched:
		if len(data) >= 4 {
			lastMs := binary.BigEndian.Uint32(data)
			deltaMs := int64(sysUptime) - int64(lastMs)
			rec.TimestampEnd = baseTime.Add(-time.Duration(deltaMs) * time.Millisecond)
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
		return 0
	}
}

// TemplateCount returns the number of cached templates.
func (p *V9Parser) TemplateCount() int {
	p.templatesMu.RLock()
	defer p.templatesMu.RUnlock()

	count := 0
	for _, sourceTemplates := range p.templates {
		count += len(sourceTemplates)
	}
	return count
}
