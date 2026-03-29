# AIS Codec

Encode vessel position and voyage data into AIS (Automatic Identification System) audio WAV files and decode AIS WAV recordings back into vessel information.

AIS is the International Maritime Organization (IMO) mandated vessel tracking system used on all ships over 300 gross tons on international voyages. It broadcasts vessel identity, position, course, and speed on VHF marine channels using GMSK modulation at 9600 bps.

## Quick Start

### Prerequisites

```bash
pip install numpy --break-system-packages
```

### Encoding: Create an AIS transmission

Create a Type 1 position report for a vessel at Boston:

```bash
python3 scripts/ais_encode.py output.wav \
  --mmsi 211376240 \
  --lat 42.3601 \
  --lon -71.0589 \
  --sog 8.5 \
  --cog 270.0 \
  --heading 270
```

Create a Type 5 static data message with vessel information:

```bash
python3 scripts/ais_encode.py vessel_info.wav \
  --type 5 \
  --mmsi 211376240 \
  --name "BOSTON BELLE" \
  --callsign "WBHX" \
  --imo 1234567 \
  --destination "NEW YORK" \
  --ship-type 70
```

### Decoding: Extract information from AIS audio

```bash
python3 scripts/ais_decode.py output.wav decoded.txt
```

Or print to stdout:

```bash
python3 scripts/ais_decode.py output.wav
```

### Testing

Run the comprehensive test suite:

```bash
python3 scripts/ais_test.py [--verbose]
```

## How It Works

### AIS Message Structure

An AIS transmission contains:

1. **Training sequence** — 24 alternating bits (0101...01) for bit synchronization
2. **Start flag** — HDLC 0x7E (01111110)
3. **Data payload** — Variable length depending on message type
4. **CRC-16-CCITT** — 16-bit Frame Check Sequence for error detection
5. **End flag** — HDLC 0x7E
6. **Buffer** — 24 trailing bits

The data is NRZI-encoded (0 = transition, 1 = no transition) and bit-stuffed
(a 0 is inserted after five consecutive 1-bits) before transmission.

### GMSK Modulation

The bitstream is modulated using GMSK (Gaussian Minimum Shift Keying):
- Data rate: 9600 bps
- Center frequency: 2400 Hz (audio baseband)
- Sample rate: 48000 Hz (5 samples per bit)
- BT product: 0.4 (Gaussian filter bandwidth-time product)

### Message Types

The skill supports the most common AIS message types:

- **Type 1, 2, 3**: Position Report Class A
  - MMSI, status, position, speed, course, heading, timestamp
- **Type 5**: Static and Voyage Related Data
  - MMSI, IMO, callsign, vessel name, dimensions, destination, ETA
- **Type 18**: Standard Class B Position Report
  - Similar to Type 1, for Class B vessels
- **Type 24**: Class B Static Data
  - MMSI, vessel name, ship type, dimensions

### Payload Encoding

- **6-bit ASCII**: Text fields (name, callsign, etc.) use AIS 6-bit encoding
- **Position**: Latitude and longitude encoded with 1/600,000 degree precision
- **Speed**: Speed over ground in 1/10 knot units (10-bit unsigned)
- **Course**: Course over ground in 1/10 degree units (12-bit unsigned)

## Scripts

### ais_encode.py

```
Usage: ais_encode.py <output.wav> [options]

Options:
  --type N           Message type (1, 5, 18, 24; default 1)
  --mmsi NNNNNNNNN   9-digit MMSI (default 211234567)
  --lat DD.DDDDDD    Latitude in decimal degrees (default 42.0)
  --lon DD.DDDDDD    Longitude in decimal degrees (default -70.0)
  --sog N.N          Speed over ground in knots (default 10.5)
  --cog N.N          Course over ground in degrees (default 180.0)
  --heading N        True heading 0-359 (default 511 = N/A)
  --rot N            Rate of turn in degrees/minute (default 0)
  --nav-status N     Navigation status 0-15 (default 0)
  --name TEXT        Vessel name up to 20 chars (Type 5/24)
  --callsign TEXT    Callsign up to 7 chars (Type 5)
  --destination TEXT Destination up to 20 chars (Type 5)
  --imo NNNNNNN      IMO number 7 digits (Type 5)
  --ship-type N      Ship and cargo type 0-99 (Type 5)
```

### ais_decode.py

```
Usage: ais_decode.py <input.wav> [output.txt]
```

Decodes an AIS WAV and outputs:
- Message type
- Decoded fields (MMSI, position, speed, heading, vessel name, etc.)
- CRC verification status

### ais_test.py

```
Usage: ais_test.py [--verbose]
```

Runs validation tests covering:
- 6-bit ASCII encoding/decoding
- Position encoding precision
- Bit packing utilities
- NRZI encoding/decoding
- CRC-16 calculation
- Message type builders
- GMSK modulation/demodulation
- Full encode/decode roundtrips

## Technical Details

### AIS 6-bit Text Encoding

AIS uses a compact 6-bit character set:
- Values 0-31: Characters '@' through '_' (ASCII 0x40-0x5F)
- Values 32-63: Characters ' ' through '?' (ASCII 0x20-0x3F)

Space becomes character 32, and punctuation is limited. Names and callsigns
are padded with '@' characters to fill their field width.

### CRC Calculation

The CRC-16-CCITT polynomial is 0x1021 with an initial value of 0xFFFF.
The CRC is inverted (XOR with 0xFFFF) before transmission and verified
on reception.

### GMSK Demodulation

The decoder estimates instantaneous frequency using an FM discriminator,
applies Gaussian matched filtering, and samples at bit centers. This approach
handles the continuous-phase nature of GMSK without losing sync.

## Examples

### Encode a position report for a fishing vessel

```bash
python3 scripts/ais_encode.py fishing_report.wav \
  --type 1 \
  --mmsi 265123456 \
  --lat 44.2121 \
  --lon -67.5289 \
  --sog 5.2 \
  --cog 45.0 \
  --heading 48
```

### Encode a vessel static data transmission

```bash
python3 scripts/ais_encode.py ship_data.wav \
  --type 5 \
  --mmsi 251000000 \
  --name "NORDIC QUEEN" \
  --callsign "SXYZ1" \
  --imo 9123456 \
  --ship-type 70 \
  --destination "ROTTERDAM" \
  --imo 9123456
```

### Decode and inspect a recorded AIS signal

```bash
python3 scripts/ais_decode.py recording.wav report.txt
cat report.txt
```

## References

- ITU-R M.1371-5: Technical characteristics of a Universal Shipborne Automatic Identification System (AIS)
- GMSK modulation: Continuous-phase frequency modulation with Gaussian filtering
- HDLC framing: CCITT X.25
