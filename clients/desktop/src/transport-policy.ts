/**
 * Which server / download URLs the companion will talk to over the wire.
 *
 * The API token travels as a Bearer header on every request, and mod archives
 * are unpacked into install folders. Over plain `http://` on the open internet
 * both are open to anyone on the path, so `http://` is accepted only for hosts
 * that are on the user's own machine or network. `https://` is always fine.
 *
 * Rust (`validate_server_base_url` in `src-tauri/src/lib.rs`) applies the same
 * rules to the saved config — keep the two in step. `fixtures/server-urls.json`
 * lists URLs with the verdict both must give; the vitest and cargo tests each read
 * it, so a change to one side that the other does not follow fails a test.
 */

export type TransportCheck = { ok: true; url: URL } | { ok: false; message: string }

/**
 * House-network host suffixes a router hands out. The same suffixes as
 * `_PRIVATE_SUFFIXES` in `oneirodex/utils/trusted_host.py`; the address ranges
 * below are the companion's own list.
 */
const PRIVATE_HOST_SUFFIXES = ['.local', '.lan', '.home.arpa', '.internal', '.localdomain']

const HTTP_LOCAL_HINT =
  'plain http:// is only allowed for localhost, private LAN or Tailscale addresses, and .local, .lan, .home.arpa, .internal or .localdomain names'

/** Parse a dotted-quad from `URL.hostname` (WHATWG already folded 0x7f.1 and friends). */
function parseIpv4(host: string): [number, number, number, number] | null {
  const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host)
  if (!match) {
    return null
  }
  const octets = match.slice(1).map(Number)
  if (octets.some((octet) => octet > 255)) {
    return null
  }
  return [octets[0]!, octets[1]!, octets[2]!, octets[3]!]
}

/**
 * 127/8, 10/8, 172.16/12, 192.168/16, 169.254/16 and the shared address space
 * 100.64/10 (RFC 6598), where Tailscale puts every peer. Tailscale encrypts the
 * hop. Accepting that range is the companion's own call; the backend's rule for
 * it is the SSRF filter (`_is_blocked_ip` in `oneirodex/utils/security.py`),
 * which counts it as non-public home-lab space.
 */
function isPrivateOrLoopbackIpv4([a, b]: [number, number, number, number]): boolean {
  return (
    a === 127 ||
    a === 10 ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 169 && b === 254) ||
    (a === 100 && b >= 64 && b <= 127)
  )
}

/**
 * Parse the bracket-less, canonical IPv6 text `URL.hostname` produces into its
 * eight 16-bit groups. Anything unexpected (dotted tails, stray characters)
 * returns null, which callers treat as "not local".
 */
function parseIpv6(host: string): number[] | null {
  if (!/^[0-9a-f:]+$/.test(host)) {
    return null
  }
  const halves = host.split('::')
  if (halves.length > 2) {
    return null
  }
  const toGroups = (part: string): number[] | null => {
    if (part === '') {
      return []
    }
    const groups = part
      .split(':')
      .map((group) => (/^[0-9a-f]{1,4}$/.test(group) ? parseInt(group, 16) : NaN))
    return groups.some(Number.isNaN) ? null : groups
  }
  const head = toGroups(halves[0]!)
  const tail = halves.length === 2 ? toGroups(halves[1]!) : []
  if (!head || !tail) {
    return null
  }
  if (halves.length === 1) {
    return head.length === 8 ? head : null
  }
  const missing = 8 - head.length - tail.length
  if (missing < 1) {
    return null
  }
  return [...head, ...Array<number>(missing).fill(0), ...tail]
}

/**
 * `::1`, unique-local fc00::/7 (which holds Tailscale's fd7a:115c:a1e0::/48),
 * link-local fe80::/10, or a mapped local IPv4.
 */
function isPrivateOrLoopbackIpv6(groups: number[]): boolean {
  const first = groups[0]!
  const isLoopback = groups.slice(0, 7).every((group) => group === 0) && groups[7] === 1
  if (isLoopback || (first & 0xfe00) === 0xfc00 || (first & 0xffc0) === 0xfe80) {
    return true
  }
  const isV4Mapped = groups.slice(0, 5).every((group) => group === 0) && groups[5] === 0xffff
  if (isV4Mapped) {
    const high = groups[6]!
    const low = groups[7]!
    return isPrivateOrLoopbackIpv4([high >> 8, high & 0xff, low >> 8, low & 0xff])
  }
  return false
}

/**
 * Does this `URL.hostname` name a machine on the user's own network?
 *
 * Literal local address ranges, the house-network suffixes (`*.local` mDNS,
 * `*.lan`, `*.home.arpa`, `*.internal`, `*.localdomain`), and a bare single-label
 * name (`nas`, `localhost`) that only the local resolver can answer. A dotted
 * public name never qualifies, however much it reads like an address
 * (`192.168.1.1.evil.com`).
 */
export function isPrivateOrLoopbackHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase()
  if (host.startsWith('[') && host.endsWith(']')) {
    const groups = parseIpv6(host.slice(1, -1))
    return groups !== null && isPrivateOrLoopbackIpv6(groups)
  }
  // `URL.hostname` is already an IPv4 address when the host is one (WHATWG folds
  // `0x7f.1` and a single trailing dot). Two trailing dots leave a *domain name*
  // that only reads like an address (`127.0.0.1..`), which Rust's `url` crate
  // also keeps as a domain, so the dotted-quad test must see the host as it is.
  const ipv4 = parseIpv4(host)
  if (ipv4) {
    return isPrivateOrLoopbackIpv4(ipv4)
  }
  const name = host.replace(/\.+$/, '')
  const suffix = PRIVATE_HOST_SUFFIXES.find((candidate) => name.endsWith(candidate))
  if (suffix) {
    return name.length > suffix.length
  }
  return name !== '' && !name.includes('.')
}

const PUNY_BASE = 36
const PUNY_TMIN = 1
const PUNY_TMAX = 26
const PUNY_SKEW = 38
const PUNY_DAMP = 700
const PUNY_INITIAL_BIAS = 72
const PUNY_INITIAL_N = 128
const PUNY_MAX_INT = 0x7fffffff

function punyAdapt(delta: number, numPoints: number, first: boolean): number {
  let scaled = first ? Math.floor(delta / PUNY_DAMP) : delta >> 1
  scaled += Math.floor(scaled / numPoints)
  let k = 0
  while (scaled > ((PUNY_BASE - PUNY_TMIN) * PUNY_TMAX) >> 1) {
    scaled = Math.floor(scaled / (PUNY_BASE - PUNY_TMIN))
    k += PUNY_BASE
  }
  return Math.floor(k + ((PUNY_BASE - PUNY_TMIN + 1) * scaled) / (scaled + PUNY_SKEW))
}

function punyDigit(code: number): number {
  if (code >= 0x30 && code <= 0x39) {
    return code - 0x30 + 26
  }
  if (code >= 0x61 && code <= 0x7a) {
    return code - 0x61
  }
  if (code >= 0x41 && code <= 0x5a) {
    return code - 0x41
  }
  return PUNY_BASE
}

/** RFC 3492 decode of what follows `xn--`: its code points, or null when it is not valid punycode. */
function decodePunycode(input: string): number[] | null {
  const output: number[] = []
  let basic = input.lastIndexOf('-')
  if (basic < 0) {
    basic = 0
  }
  for (let j = 0; j < basic; j++) {
    if (input.charCodeAt(j) >= 0x80) {
      return null
    }
    output.push(input.charCodeAt(j))
  }
  let n = PUNY_INITIAL_N
  let i = 0
  let bias = PUNY_INITIAL_BIAS
  let index = basic > 0 ? basic + 1 : 0
  while (index < input.length) {
    const previous = i
    let weight = 1
    for (let k = PUNY_BASE; ; k += PUNY_BASE) {
      if (index >= input.length) {
        return null
      }
      const digit = punyDigit(input.charCodeAt(index++))
      if (digit >= PUNY_BASE || digit > Math.floor((PUNY_MAX_INT - i) / weight)) {
        return null
      }
      i += digit * weight
      const threshold = k <= bias ? PUNY_TMIN : k >= bias + PUNY_TMAX ? PUNY_TMAX : k - bias
      if (digit < threshold) {
        break
      }
      if (weight > Math.floor(PUNY_MAX_INT / (PUNY_BASE - threshold))) {
        return null
      }
      weight *= PUNY_BASE - threshold
    }
    const length = output.length + 1
    bias = punyAdapt(i - previous, length, previous === 0)
    if (Math.floor(i / length) > PUNY_MAX_INT - n) {
      return null
    }
    n += Math.floor(i / length)
    i %= length
    if (n > 0x10ffff || (n >= 0xd800 && n <= 0xdfff)) {
      return null
    }
    output.splice(i++, 0, n)
  }
  return output
}

/**
 * Is this one DNS label something Rust's `url` crate (IDNA, UTS 46) accepts? An
 * `xn--` label has to be valid punycode that decodes to something other than
 * plain ASCII, with no control character in it. Node's `new URL` lets `xn--nas-`
 * through, the crate refuses the whole URL, and so `save_config` would turn down
 * a URL this check had waved on.
 *
 * Only checks that do not depend on a Unicode version are made here. The crate
 * also refuses labels that decode to unassigned or non-NFC text; for those the
 * Rust side stays the backstop.
 */
function isAcceptableDnsLabel(label: string): boolean {
  if (!/^xn--/i.test(label)) {
    return true
  }
  const decoded = decodePunycode(label.slice(4))
  return (
    decoded !== null &&
    decoded.some((point) => point > 0x7f) &&
    !decoded.some((point) => point < 0x20 || (point >= 0x7f && point <= 0x9f))
  )
}

/** False for a host name with a label the `url` crate would refuse. IP literals pass. */
export function hasAcceptableDnsLabels(hostname: string): boolean {
  if (hostname.startsWith('[')) {
    return true
  }
  return hostname.split('.').every(isAcceptableDnsLabel)
}

function checkTransportUrl(
  raw: string,
  notValid: string,
  insecure: (host: string) => string,
  otherScheme: string,
): TransportCheck {
  let url: URL
  try {
    url = new URL(raw.trim())
  } catch {
    return { ok: false, message: notValid }
  }
  if (!hasAcceptableDnsLabels(url.hostname)) {
    return { ok: false, message: notValid }
  }
  if (url.protocol === 'https:') {
    return { ok: true, url }
  }
  if (url.protocol === 'http:') {
    if (isPrivateOrLoopbackHost(url.hostname)) {
      return { ok: true, url }
    }
    return { ok: false, message: insecure(url.hostname) }
  }
  return { ok: false, message: otherScheme }
}

/**
 * The Oneirodex server URL. Refusing here means the token is never attached to a
 * request for a server reached over plain `http://` on the internet.
 */
export function checkServerUrl(raw: string): TransportCheck {
  return checkTransportUrl(
    raw,
    'Server URL is not a valid URL. Start it with https:// (or http:// for a server on your own network).',
    (host) =>
      `Refusing http:// for ${host}: your API token would be sent unencrypted. Use an https:// server URL (${HTTP_LOCAL_HINT}).`,
    'Server URL must start with https:// (or http:// for a server on your own network).',
  )
}

/**
 * Why a server URL saved by an earlier build is refused now, or `null` when it is
 * still acceptable. Shown on start-up so a seat does not sit silently idle: a
 * saved `http://` URL the policy no longer allows never reaches the auth store,
 * so presence and Connect quietly do nothing unless the reason is put in front of
 * the user.
 */
export function savedServerUrlProblem(raw: string): string | null {
  if (!raw.trim()) {
    return null
  }
  const check = checkServerUrl(raw)
  return check.ok ? null : check.message
}

/**
 * The URL an archive download ended on after redirects (`response.url`; the
 * legs in between are not visible to `fetch`). Same `http://`-only-on-your-own-
 * network rule as the server and mod sources: an archive that can be rewritten in
 * transit is unpacked into a game folder and later launched.
 */
export function checkDownloadRedirectUrl(raw: string): TransportCheck {
  return checkTransportUrl(
    raw,
    'The download was redirected to a URL that is not valid. It must start with https://.',
    (host) =>
      `Refusing http:// download redirect to ${host}: the archive could be tampered with in transit. The server should redirect to an https:// URL (${HTTP_LOCAL_HINT}).`,
    'The download was redirected to a URL that must start with https:// (http:// is only allowed on your own network).',
  )
}

/**
 * An admin-supplied mod `source_url`. The archive is unpacked into a game folder,
 * so a download that can be rewritten in transit is refused up front.
 */
export function checkModSourceUrl(raw: string): TransportCheck {
  return checkTransportUrl(
    raw,
    'Mod source URL is not a valid URL. It must start with https://.',
    (host) =>
      `Refusing http:// mod source ${host}: the download could be tampered with in transit. Use an https:// source URL (${HTTP_LOCAL_HINT}).`,
    'Mod source URL must start with https:// (http:// is only allowed on your own network).',
  )
}
