#!/usr/bin/env python3
"""
Shared module for AIS (Automatic Identification System) encoding/decoding.

Contains:
  - AIS message structure and field definitions
  - 6-bit ASCII encoding/decoding for AIS
  - CRC-16-CCITT calculation
  - Bit packing/unpacking utilities
  - NRZI encoding/decoding
  - Bit stuffing/unstuffing (HDLC-style)
  - GMSK modulation/demodulation
  - Message type builders (Type 1, 5, 18, 24)
  - AIS payload parser

AIS signal structure:
  [Training: 24 bits] [Start flag: 0x7E] [Data: payload + CRC, bit-stuffed]
  [End flag: 0x7E] [Buffer: 24 bits]

  Data is NRZI-encoded: 0 = transition, 1 = no transition.
  Bit stuffing: insert 0 after five consecutive 1s.
  CRC-16-CCITT (poly 0x1021) is computed on unstuffed data, then inverted.

GMSK parameters:
  - Data rate: 9600 bps
  - Sample rate: 48000 Hz (5 samples per bit)
  - BT product: 0.4
  - Center frequency: 2400 Hz
"""

import numpy as np
from struct import pack, unpack

# ============================================================================
# Constants
# ============================================================================

SAMPLE_RATE = 48000          # Higher rate for 9600 bps (5 samples/bit)
DATA_RATE = 9600            # AIS data rate in bps
CENTER_FREQ = 2400.0        # GMSK center frequency for audio baseband
BT = 0.4                    # Gaussian filter BT product
HDLC_FLAG = 0x7E           # HDLC flag byte (01111110 in binary)

# ============================================================================
# 6-bit ASCII Encoding (AIS variant)
# ============================================================================

def ais_6bit_encode(text):
    """
    Encode text to AIS 6-bit ASCII.

    AIS 6-bit encoding:
      Characters 0x40-0x5F (@-_) map to 0-31
      Characters 0x20-0x3F (space-?) map to 32-63

    Args:
        text: String to encode

    Returns:
        List of 6-bit values (0-63)
    """
    result = []
    for ch in text.upper():
        code = ord(ch)
        # Map ASCII to 6-bit AIS encoding
        if 0x40 <= code <= 0x5F:
            result.append(code - 0x40)
        elif 0x20 <= code <= 0x3F:
            result.append(code - 0x20 + 32)
        else:
            result.append(0)  # Default to '@'
    return result


def ais_6bit_decode(bits):
    """
    Decode AIS 6-bit ASCII back to text.

    Args:
        bits: List of 6-bit values (0-63)

    Returns:
        Decoded string
    """
    result = []
    for val in bits:
        val = val & 0x3F
        if val < 32:
            result.append(chr(val + 0x40))
        else:
            result.append(chr(val - 32 + 0x20))
    return ''.join(result)


# ============================================================================
# Position Encoding/Decoding
# ============================================================================

def encode_position(lat, lon):
    """
    Encode latitude and longitude to AIS bit format.

    AIS encoding:
      Latitude: 27-bit signed integer, value / 600,000 = degrees
      Longitude: 28-bit signed integer, value / 600,000 = degrees

    Args:
        lat: Latitude in decimal degrees (-90 to 90)
        lon: Longitude in decimal degrees (-180 to 180)

    Returns:
        Tuple (lon_bits, lat_bits) as integers ready for packing
    """
    lat_int = int(lat * 600000)
    lon_int = int(lon * 600000)

    # Clamp to bit widths and handle signed representation
    lat_int = max(-2**26, min(2**26 - 1, lat_int))
    lon_int = max(-2**27, min(2**27 - 1, lon_int))

    return lon_int, lat_int


def decode_position(lon_bits, lat_bits):
    """
    Decode AIS position bits back to latitude and longitude.

    Args:
        lon_bits: 28-bit signed integer
        lat_bits: 27-bit signed integer

    Returns:
        Tuple (latitude, longitude) in decimal degrees
    """
    # The values are already signed integers from unpacking.
    # No additional two's complement conversion needed.
    lat = lat_bits / 600000.0
    lon = lon_bits / 600000.0

    return lat, lon


# ============================================================================
# Bit Packing/Unpacking Utilities
# ============================================================================

def pack_uint(value, width):
    """Pack an unsigned integer into a list of bits."""
    bits = []
    for i in range(width):
        bits.append((value >> i) & 1)
    return bits


def pack_sint(value, width):
    """Pack a signed integer (two's complement) into a list of bits."""
    if value < 0:
        value = (1 << width) + value
    return pack_uint(value, width)


def unpack_uint(bits, width):
    """Unpack an unsigned integer from a list of bits."""
    result = 0
    for i in range(min(width, len(bits))):
        result |= (bits[i] & 1) << i
    return result


def unpack_sint(bits, width):
    """Unpack a signed integer (two's complement) from a list of bits."""
    result = unpack_uint(bits, width)
    if result & (1 << (width - 1)):
        result = result - (1 << width)
    return result


# ============================================================================
# Bit Stuffing / Unstuffing (HDLC)
# ============================================================================

def bit_stuff(bits):
    """
    Insert a 0 bit after every five consecutive 1-bits (HDLC bit stuffing).

    Args:
        bits: List of 0/1 integers

    Returns:
        Bit-stuffed list
    """
    result = []
    ones_count = 0

    for bit in bits:
        result.append(bit)
        if bit == 1:
            ones_count += 1
            if ones_count == 5:
                result.append(0)  # Insert stuffing bit
                ones_count = 0
        else:
            ones_count = 0

    return result


def bit_unstuff(bits):
    """
    Remove stuffed 0 bits (bits inserted after five consecutive 1s).

    Args:
        bits: Bit-stuffed list

    Returns:
        Unstuffed list
    """
    result = []
    ones_count = 0
    i = 0

    while i < len(bits):
        bit = bits[i]

        if bit == 1:
            result.append(bit)
            ones_count += 1
            if ones_count == 5 and i + 1 < len(bits):
                # Next bit should be a stuffed 0; skip it
                i += 1
                ones_count = 0
        else:
            result.append(bit)
            ones_count = 0

        i += 1

    return result


# ============================================================================
# NRZI Encoding/Decoding
# ============================================================================

def nrzi_encode(bits):
    """
    NRZI encoding: 0 = transition, 1 = no transition.

    Produces a bitstream of carrier states. The first state is always 1.

    Args:
        bits: List of 0/1 integers (data bits)

    Returns:
        NRZI-encoded bitstream (carrier states)
    """
    result = []
    current = 1  # Start with mark (1)

    for bit in bits:
        if bit == 0:
            current = 1 - current  # Transition
        result.append(current)

    return result


def nrzi_decode(bits):
    """
    NRZI decoding: detect transitions in carrier to recover data bits.

    A transition (bit changes from previous) means data bit 0.
    No transition means data bit 1.

    Args:
        bits: NRZI-encoded bitstream (carrier states)

    Returns:
        Original data bits (one fewer than input due to differential detection)
    """
    if len(bits) == 0:
        return []

    result = []
    prev = 1  # Assume we started in mark state

    for i in range(len(bits)):
        if bits[i] != prev:
            result.append(0)  # Transition = 0
        else:
            result.append(1)  # No transition = 1
        prev = bits[i]

    # We got one extra result. Remove the last one since we had N+1 state comparisons
    # Actually, we have N comparisons (comparing each of N states to the previous state)
    # So we get N results, which is correct (N input states -> N-1 transitions, but we
    # compare each state to previous, so N comparisons -> N outputs)
    # This is actually OK because the first comparison is state[0] vs initial state (1)

    return result[:-1]  # Return N-1 bits from N input states


# ============================================================================
# CRC-16-CCITT
# ============================================================================

def crc16_ccitt(bits):
    """
    Calculate CRC-16-CCITT on a bitstream.

    Polynomial: 0x1021
    Initial value: 0xFFFF
    The CRC is inverted (XOR with 0xFFFF) before transmission.

    Args:
        bits: List of 0/1 integers (data bits, not bit-stuffed)

    Returns:
        16-bit CRC value
    """
    crc = 0xFFFF

    for bit in bits:
        # XOR bit into MSB of CRC
        msb = (crc >> 15) & 1
        crc = (crc << 1) & 0xFFFF
        if msb ^ bit:
            crc ^= 0x1021

    return crc


# ============================================================================
# GMSK Modulation
# ============================================================================

def gmsk_modulate(bits, sample_rate=SAMPLE_RATE, data_rate=DATA_RATE,
                  bt=BT, center_freq=CENTER_FREQ):
    """
    GMSK modulate a bitstream to audio.

    GMSK: data is filtered with a Gaussian LPF (BT parameter), then
    used to frequency-modulate a carrier. For audio baseband, the carrier
    is the center frequency.

    Process:
      1. Map bits to +1/-1
      2. Apply Gaussian filter (BT=0.4)
      3. Integrate filtered signal to get phase modulation
      4. Generate cos(2π*fc*t + phase)

    Args:
        bits: List of 0/1 integers
        sample_rate: Audio sample rate (Hz)
        data_rate: Data rate (bps)
        bt: Gaussian filter BT product
        center_freq: Center frequency for modulation (Hz)

    Returns:
        numpy array of float64 audio samples in [-1, 1]
    """
    # Map bits to +1/-1
    symbols = np.array([1.0 if b else -1.0 for b in bits], dtype=np.float64)

    samples_per_bit = sample_rate / data_rate

    # Upsample to sample rate
    n_samples = int(np.ceil(len(symbols) * samples_per_bit))
    upsampled = np.zeros(n_samples, dtype=np.float64)

    for i, sym in enumerate(symbols):
        idx = int(i * samples_per_bit)
        if idx < n_samples:
            upsampled[idx] = sym

    # Design Gaussian filter
    # BT = 0.4 means the 3dB bandwidth of the Gaussian filter times the
    # bit period equals 0.4. The standard deviation is related to BT.
    sigma = 1.0 / (2 * np.pi * bt / samples_per_bit)
    filter_len = max(8, int(4 * sigma))
    if filter_len % 2 == 0:
        filter_len += 1

    t_filt = np.arange(filter_len) - filter_len // 2
    gaussian = np.exp(-(t_filt ** 2) / (2 * sigma ** 2))
    gaussian /= np.sum(gaussian)

    # Apply Gaussian filter
    filtered = np.convolve(upsampled, gaussian, mode='same')

    # Integrate to get phase (FM modulation index)
    # For GMSK, the phase deviation is related to the filtered symbol
    phase = np.cumsum(filtered) * (2 * np.pi * data_rate / sample_rate)

    # Generate modulated signal
    t = np.arange(n_samples, dtype=np.float64) / sample_rate
    carrier = np.cos(2 * np.pi * center_freq * t + phase)

    return carrier


# ============================================================================
# GMSK Demodulation
# ============================================================================

def gmsk_demodulate(audio, sample_rate=SAMPLE_RATE, data_rate=DATA_RATE,
                    bt=BT, center_freq=CENTER_FREQ):
    """
    GMSK demodulate audio back to a bitstream.

    Process:
      1. FM discriminator: estimate instantaneous frequency
      2. Low-pass filtering
      3. Sample at bit centers
      4. Threshold detect

    Args:
        audio: numpy array of audio samples
        sample_rate: Audio sample rate (Hz)
        data_rate: Data rate (bps)
        bt: Gaussian filter BT product
        center_freq: Center frequency (Hz)

    Returns:
        List of 0/1 integers (demodulated bits)
    """
    # Demodulate (mix down to baseband and extract phase)
    t = np.arange(len(audio), dtype=np.float64) / sample_rate
    cos_term = np.cos(2 * np.pi * center_freq * t)
    sin_term = np.sin(2 * np.pi * center_freq * t)

    i_sig = audio * cos_term
    q_sig = audio * sin_term

    # Low-pass filter to smooth
    cutoff = data_rate * 1.5
    window_len = max(8, int(sample_rate / cutoff / 2))
    if window_len % 2 == 0:
        window_len += 1

    kernel = np.ones(window_len) / window_len
    i_filt = np.convolve(i_sig, kernel, mode='same')
    q_filt = np.convolve(q_sig, kernel, mode='same')

    # Instantaneous frequency (FM discriminator)
    # freq = d(phase)/dt = Im(dz/dt * conj(z)) / |z|^2
    di = np.diff(i_filt)
    dq = np.diff(q_filt)
    i_filt_c = i_filt[:-1]
    q_filt_c = q_filt[:-1]

    numerator = i_filt_c * dq - q_filt_c * di
    denominator = i_filt_c ** 2 + q_filt_c ** 2

    with np.errstate(divide='ignore', invalid='ignore'):
        inst_freq = np.arctan2(numerator, denominator) * sample_rate / (2 * np.pi)
    inst_freq = np.nan_to_num(inst_freq, nan=0.0)

    # Pad to match original length
    inst_freq = np.concatenate([inst_freq, [inst_freq[-1] if len(inst_freq) > 0 else 0]])

    # Further smooth the frequency estimate
    smooth_kernel = np.ones(max(3, window_len // 4)) / max(3, window_len // 4)
    inst_freq = np.convolve(inst_freq, smooth_kernel, mode='same')

    # Sample at bit centers
    samples_per_bit = sample_rate / data_rate
    bits = []

    for i in range(int(len(audio) / samples_per_bit)):
        idx = int((i + 0.5) * samples_per_bit)
        if idx < len(inst_freq):
            # Threshold at 0 frequency
            freq_val = inst_freq[idx]
            bits.append(1 if freq_val >= 0 else 0)

    return bits


# ============================================================================
# AIS Message Builders
# ============================================================================

def build_ais_type1(mmsi, nav_status=0, rot=0, sog=0, lon=0, lat=0,
                    cog=0, heading=511, timestamp=0):
    """
    Build an AIS Type 1 (Position Report Class A) message.

    Args:
        mmsi: 9-digit MMSI number
        nav_status: Navigation status (0-15)
        rot: Rate of turn (-128 to 127 degrees/min)
        sog: Speed over ground in 1/10 knot units (0-102.2 knots)
        lon: Longitude in decimal degrees
        lat: Latitude in decimal degrees
        cog: Course over ground in 1/10 degree units (0-359.9)
        heading: True heading 0-359, or 511 for not available
        timestamp: UTC second (0-59)

    Returns:
        List of bits (unstuffed, ready for CRC/HDLC framing)
    """
    bits = []

    # Message Type (6 bits)
    bits.extend(pack_uint(1, 6))

    # Repeat indicator (2 bits)
    bits.extend(pack_uint(0, 2))

    # MMSI (30 bits)
    bits.extend(pack_uint(mmsi, 30))

    # Status (4 bits)
    bits.extend(pack_uint(nav_status, 4))

    # ROT (8 bits, signed)
    bits.extend(pack_sint(rot, 8))

    # SOG (10 bits) - in 1/10 knot units
    sog_int = int(sog * 10)
    bits.extend(pack_uint(sog_int, 10))

    # Position accuracy (1 bit)
    bits.extend(pack_uint(0, 1))

    # Longitude (28 bits, signed)
    lon_int, lat_int = encode_position(lat, lon)
    bits.extend(pack_sint(lon_int, 28))

    # Latitude (27 bits, signed)
    bits.extend(pack_sint(lat_int, 27))

    # COG (12 bits) - in 1/10 degree units
    cog_int = int(cog * 10) % 3600
    bits.extend(pack_uint(cog_int, 12))

    # Heading (9 bits)
    bits.extend(pack_uint(heading, 9))

    # Time stamp (6 bits)
    bits.extend(pack_uint(timestamp, 6))

    # Spare (2 bits)
    bits.extend(pack_uint(0, 2))

    return bits


def build_ais_type5(mmsi, imo=0, callsign="", vessel_name="", ship_type=0,
                    dim_a=0, dim_b=0, dim_c=0, dim_d=0, destination="",
                    eta_month=0, eta_day=0, eta_hour=24, eta_minute=60, draught=0):
    """
    Build an AIS Type 5 (Static and Voyage Related Data) message.

    Args:
        mmsi: 9-digit MMSI
        imo: IMO number (0 if not available)
        callsign: Callsign (7 chars max)
        vessel_name: Vessel name (20 chars max)
        ship_type: Ship and cargo type (0-99)
        dim_a, dim_b, dim_c, dim_d: Vessel dimensions in meters
        destination: Destination port (20 chars max)
        eta_month, eta_day: ETA (month 0-12, day 0-31)
        eta_hour, eta_minute: ETA time (hour 0-23, minute 0-59)
        draught: Maximum draught (1/10 meter units)

    Returns:
        List of bits (unstuffed)
    """
    bits = []

    # Message Type (6 bits)
    bits.extend(pack_uint(5, 6))

    # Repeat indicator (2 bits)
    bits.extend(pack_uint(0, 2))

    # MMSI (30 bits)
    bits.extend(pack_uint(mmsi, 30))

    # AIS version (2 bits)
    bits.extend(pack_uint(0, 2))

    # IMO (30 bits)
    bits.extend(pack_uint(imo, 30))

    # Call sign (7 x 6-bit chars = 42 bits)
    callsign_bits = ais_6bit_encode(callsign[:7].ljust(7))
    for val in callsign_bits:
        bits.extend(pack_uint(val, 6))

    # Vessel name (20 x 6-bit chars = 120 bits)
    vessel_bits = ais_6bit_encode(vessel_name[:20].ljust(20))
    for val in vessel_bits:
        bits.extend(pack_uint(val, 6))

    # Ship type (8 bits)
    bits.extend(pack_uint(ship_type, 8))

    # Dimension (30 bits): A(9) B(9) C(6) D(6)
    bits.extend(pack_uint(dim_a, 9))
    bits.extend(pack_uint(dim_b, 9))
    bits.extend(pack_uint(dim_c, 6))
    bits.extend(pack_uint(dim_d, 6))

    # Position fix (4 bits)
    bits.extend(pack_uint(0, 4))

    # ETA (20 bits): month(4) day(5) hour(5) minute(6)
    bits.extend(pack_uint(eta_month, 4))
    bits.extend(pack_uint(eta_day, 5))
    bits.extend(pack_uint(eta_hour, 5))
    bits.extend(pack_uint(eta_minute, 6))

    # Maximum draught (8 bits, in 1/10 m)
    draught_int = int(draught * 10)
    bits.extend(pack_uint(draught_int, 8))

    # Destination (20 x 6-bit = 120 bits)
    dest_bits = ais_6bit_encode(destination[:20].ljust(20))
    for val in dest_bits:
        bits.extend(pack_uint(val, 6))

    # DTE (1 bit)
    bits.extend(pack_uint(0, 1))

    # Spare (1 bit)
    bits.extend(pack_uint(0, 1))

    return bits


def build_ais_type18(mmsi, rot=0, sog=0, lon=0, lat=0, cog=0, heading=511, timestamp=0):
    """
    Build an AIS Type 18 (Standard Class B Position Report) message.

    Similar to Type 1 but for Class B vessels (no ROT field).

    Args:
        mmsi: 9-digit MMSI
        rot: Reserved/not used (typically 0)
        sog: Speed over ground in 1/10 knot units
        lon: Longitude in decimal degrees
        lat: Latitude in decimal degrees
        cog: Course over ground in 1/10 degree units
        heading: True heading 0-359, or 511 for not available
        timestamp: UTC second

    Returns:
        List of bits
    """
    bits = []

    # Message Type (6 bits)
    bits.extend(pack_uint(18, 6))

    # Repeat indicator (2 bits)
    bits.extend(pack_uint(0, 2))

    # MMSI (30 bits)
    bits.extend(pack_uint(mmsi, 30))

    # Reserved (8 bits)
    bits.extend(pack_uint(0, 8))

    # SOG (10 bits)
    sog_int = int(sog * 10)
    bits.extend(pack_uint(sog_int, 10))

    # Position accuracy (1 bit)
    bits.extend(pack_uint(0, 1))

    # Longitude (28 bits, signed)
    lon_int, lat_int = encode_position(lat, lon)
    bits.extend(pack_sint(lon_int, 28))

    # Latitude (27 bits, signed)
    bits.extend(pack_sint(lat_int, 27))

    # COG (12 bits)
    cog_int = int(cog * 10) % 3600
    bits.extend(pack_uint(cog_int, 12))

    # Heading (9 bits)
    bits.extend(pack_uint(heading, 9))

    # Time stamp (6 bits)
    bits.extend(pack_uint(timestamp, 6))

    # Spare (2 bits)
    bits.extend(pack_uint(0, 2))

    return bits


def build_ais_type24(mmsi, vessel_name="", ship_type=0, dim_a=0, dim_b=0, dim_c=0, dim_d=0):
    """
    Build an AIS Type 24 (Class B Static Data Report) message.

    Args:
        mmsi: 9-digit MMSI
        vessel_name: Vessel name (20 chars max)
        ship_type: Ship type (0-99)
        dim_a, dim_b, dim_c, dim_d: Dimensions

    Returns:
        List of bits
    """
    bits = []

    # Message Type (6 bits) — Type 24 = decimal 24
    bits.extend(pack_uint(24, 6))

    # Repeat indicator (2 bits)
    bits.extend(pack_uint(0, 2))

    # MMSI (30 bits)
    bits.extend(pack_uint(mmsi, 30))

    # Vessel name (20 x 6-bit = 120 bits)
    vessel_bits = ais_6bit_encode(vessel_name[:20].ljust(20))
    for val in vessel_bits:
        bits.extend(pack_uint(val, 6))

    # Ship type (8 bits)
    bits.extend(pack_uint(ship_type, 8))

    # Dimension (30 bits)
    bits.extend(pack_uint(dim_a, 9))
    bits.extend(pack_uint(dim_b, 9))
    bits.extend(pack_uint(dim_c, 6))
    bits.extend(pack_uint(dim_d, 6))

    # Spare (2 bits)
    bits.extend(pack_uint(0, 2))

    return bits


# ============================================================================
# AIS Payload Parser
# ============================================================================

def parse_ais_payload(bits):
    """
    Parse an AIS message payload (unstuffed, after removing HDLC frames).

    Returns a dict with message type and decoded fields.

    Args:
        bits: List of 0/1 bits (unstuffed data)

    Returns:
        Dict with message type and fields
    """
    if len(bits) < 6:
        return {"error": "Payload too short"}

    msg_type = unpack_uint(bits[0:6], 6)

    result = {"type": msg_type}

    if msg_type in [1, 2, 3]:
        # Position Report
        # Minimum bits: 6+2+30+4+8+10+1+28+27+12+9+6 = 143 (without spare bits)
        if len(bits) < 143:
            return {"error": "Type 1/2/3 payload incomplete"}

        result["mmsi"] = unpack_uint(bits[8:38], 30)
        result["status"] = unpack_uint(bits[38:42], 4)
        result["rot"] = unpack_sint(bits[42:50], 8)
        result["sog"] = unpack_uint(bits[50:60], 10) / 10.0
        lon_int = unpack_sint(bits[61:89], 28)
        lat_int = unpack_sint(bits[89:116], 27)
        lat, lon = decode_position(lon_int, lat_int)
        result["lat"] = lat
        result["lon"] = lon
        result["cog"] = unpack_uint(bits[116:128], 12) / 10.0
        result["heading"] = unpack_uint(bits[128:137], 9)
        result["timestamp"] = unpack_uint(bits[137:143], 6)

    elif msg_type == 5:
        # Static and Voyage Related Data
        if len(bits) < 424:
            return {"error": "Type 5 payload incomplete"}

        result["mmsi"] = unpack_uint(bits[8:38], 30)
        result["imo"] = unpack_uint(bits[40:70], 30)

        # Callsign
        callsign_bits = []
        for i in range(7):
            val = unpack_uint(bits[70 + i*6:70 + (i+1)*6], 6)
            callsign_bits.append(val)
        result["callsign"] = ais_6bit_decode(callsign_bits).strip()

        # Vessel name
        vessel_bits = []
        for i in range(20):
            val = unpack_uint(bits[112 + i*6:112 + (i+1)*6], 6)
            vessel_bits.append(val)
        result["vessel_name"] = ais_6bit_decode(vessel_bits).strip()

        result["ship_type"] = unpack_uint(bits[232:240], 8)
        result["dim_a"] = unpack_uint(bits[240:249], 9)
        result["dim_b"] = unpack_uint(bits[249:258], 9)
        result["dim_c"] = unpack_uint(bits[258:264], 6)
        result["dim_d"] = unpack_uint(bits[264:270], 6)

        result["eta_month"] = unpack_uint(bits[274:278], 4)
        result["eta_day"] = unpack_uint(bits[278:283], 5)
        result["eta_hour"] = unpack_uint(bits[283:288], 5)
        result["eta_minute"] = unpack_uint(bits[288:294], 6)
        result["draught"] = unpack_uint(bits[294:302], 8) / 10.0

        # Destination
        dest_bits = []
        for i in range(20):
            val = unpack_uint(bits[302 + i*6:302 + (i+1)*6], 6)
            dest_bits.append(val)
        result["destination"] = ais_6bit_decode(dest_bits).strip()

    elif msg_type == 18:
        # Standard Class B Position Report
        # Minimum bits: 6+2+30+8+10+1+28+27+12+9+6 = 139
        if len(bits) < 139:
            return {"error": "Type 18 payload incomplete"}

        result["mmsi"] = unpack_uint(bits[8:38], 30)
        result["sog"] = unpack_uint(bits[46:56], 10) / 10.0
        lon_int = unpack_sint(bits[57:85], 28)
        lat_int = unpack_sint(bits[85:112], 27)
        lat, lon = decode_position(lon_int, lat_int)
        result["lat"] = lat
        result["lon"] = lon
        result["cog"] = unpack_uint(bits[112:124], 12) / 10.0
        result["heading"] = unpack_uint(bits[124:133], 9)
        result["timestamp"] = unpack_uint(bits[133:139], 6)

    elif msg_type == 24:
        # Class B Static Data Report
        # Minimum bits: 6+2+30+120+8+9+9+6+6 = 196
        if len(bits) < 196:
            return {"error": "Type 24 payload incomplete"}

        result["mmsi"] = unpack_uint(bits[8:38], 30)

        # Vessel name
        vessel_bits = []
        for i in range(20):
            val = unpack_uint(bits[40 + i*6:40 + (i+1)*6], 6)
            vessel_bits.append(val)
        result["vessel_name"] = ais_6bit_decode(vessel_bits).strip()

        result["ship_type"] = unpack_uint(bits[160:168], 8)
        result["dim_a"] = unpack_uint(bits[168:177], 9)
        result["dim_b"] = unpack_uint(bits[177:186], 9)
        result["dim_c"] = unpack_uint(bits[186:192], 6)
        result["dim_d"] = unpack_uint(bits[192:198], 6)

    else:
        result["error"] = f"Unsupported message type: {msg_type}"

    return result
