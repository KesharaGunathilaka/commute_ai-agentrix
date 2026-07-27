/**
 * Google encoded-polyline decoding.
 *
 * Implemented here rather than via `google.maps.geometry.encoding.decodePath`
 * so route geometry can be measured and framed before the Maps SDK has
 * loaded — and so the app still has usable coordinates when no Maps key is
 * configured at all.
 *
 * Format: https://developers.google.com/maps/documentation/utilities/polylinealgorithm
 */

export interface LatLng {
  lat: number;
  lng: number;
}

/**
 * Decode an encoded polyline into its point list.
 *
 * Returns [] for empty or malformed input rather than throwing — a route
 * without drawable geometry should degrade to "no line on the map", never
 * take the page down.
 */
export function decodePolyline(encoded: string | null | undefined): LatLng[] {
  if (!encoded) return [];

  const points: LatLng[] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;

  while (index < encoded.length) {
    const latDelta = decodeSignedValue();
    if (latDelta === null) break;
    const lngDelta = decodeSignedValue();
    if (lngDelta === null) break;

    lat += latDelta;
    lng += lngDelta;
    // Values are stored as integer hundred-thousandths of a degree.
    points.push({ lat: lat / 1e5, lng: lng / 1e5 });
  }

  return points;

  /** Read one zigzag-encoded varint from the stream, or null if it's truncated. */
  function decodeSignedValue(): number | null {
    let result = 0;
    let shift = 0;
    let byte: number;

    do {
      if (index >= encoded!.length) return null;
      byte = encoded!.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);

    // Low bit is the sign flag; the rest is the magnitude.
    return result & 1 ? ~(result >> 1) : result >> 1;
  }
}

/** Smallest box containing every point, or null if there are none. */
export function boundsOf(points: LatLng[]): {
  north: number;
  south: number;
  east: number;
  west: number;
} | null {
  if (points.length === 0) return null;

  let north = points[0].lat;
  let south = points[0].lat;
  let east = points[0].lng;
  let west = points[0].lng;

  for (const { lat, lng } of points) {
    if (lat > north) north = lat;
    if (lat < south) south = lat;
    if (lng > east) east = lng;
    if (lng < west) west = lng;
  }

  return { north, south, east, west };
}
