# The machine key's signature on an uploaded report (the "signature" member,
# see ../schema/report-v1.schema.json and cli/omarchy_m_test/signing.py).
#
# The CLI signs with ssh-keygen -Y sign (an SSHSIG over an ed25519 key); this
# verifies it with Ruby's own OpenSSL rather than shelling out to ssh-keygen:
# no subprocess or temporary file per upload and no openssh in the image, and
# the SSHSIG format (PROTOCOL.sshsig in OpenSSH) is small enough to parse
# strictly here.
#
# A machine is its public key, recorded only as a keyed digest (machine_id
# "key:..."): reports group by machine, but the key itself, which would let
# anyone link a machine's reports, is never stored, shown or exported.
class MachineSignature
  class Invalid < StandardError; end

  NAMESPACE = "omarchy-m-test-report"
  # A tester's sign-in, binding their GitHub account to the machine (TesterBinding).
  TESTER_NAMESPACE = "omarchy-m-test-tester"
  KEY_TYPE = "ssh-ed25519"
  HASHES = { "sha512" => OpenSSL::Digest::SHA512, "sha256" => OpenSSL::Digest::SHA256 }.freeze
  ARMOR = /\A-----BEGIN SSH SIGNATURE-----\n([A-Za-z0-9+\/=\n]+)\n-----END SSH SIGNATURE-----\z/

  attr_reader :machine_id

  # The verified signature of `payload`, a parsed report (or, with
  # TESTER_NAMESPACE, a tester sign-in); Invalid says why not.
  def self.verify!(payload, namespace: NAMESPACE)
    new(payload.fetch("signature"), canonical(payload.except("signature")), namespace)
  end

  # The bytes the signature covers: the report as JSON with keys sorted, no
  # whitespace and non-ASCII as UTF-8, matching Python's
  # json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False).
  def self.canonical(value)
    case value
    when Hash then "{" + value.keys.sort.map { |key| "#{string(key)}:#{canonical(value[key])}" }.join(",") + "}"
    when Array then "[" + value.map { |item| canonical(item) }.join(",") + "]"
    when String then string(value)
    when Integer then value.to_s
    when true then "true"
    when false then "false"
    when nil then "null"
    else raise Invalid, "the report has a value a signed report can't have (#{value.class})"
    end
  end

  ESCAPES = { '"' => '\\"', "\\" => "\\\\", "\b" => "\\b", "\f" => "\\f", "\n" => "\\n", "\r" => "\\r", "\t" => "\\t" }.freeze

  def self.string(text)
    '"' + text.gsub(/["\\\x00-\x1f]/) { |char| ESCAPES[char] || format("\\u%04x", char.ord) } + '"'
  end

  def initialize(signature, message, expected_namespace = NAMESPACE)
    raise Invalid, "it isn't a signature object" unless signature.is_a?(Hash)

    public_key, armored = signature.values_at("public_key", "signature")
    key_blob = parse_public_key(public_key)
    sig = SshReader.new(decode(armored))
    raise Invalid, "it isn't an SSH signature" unless sig.raw(6) == "SSHSIG" && sig.uint32 == 1
    raise Invalid, "it was made with a different key than the report's public_key" unless sig.string == key_blob
    raise Invalid, "it isn't a #{expected_namespace == NAMESPACE ? "report" : "sign-in"} signature (namespace)" unless (namespace = sig.string) == expected_namespace
    reserved = sig.string
    hash_name = sig.string
    digest = HASHES[hash_name] or raise Invalid, "it uses an unknown hash (#{hash_name})"
    inner = SshReader.new(sig.string)
    sig.finish!
    raise Invalid, "it isn't an ed25519 signature" unless inner.string == KEY_TYPE
    raw_signature = inner.string
    inner.finish!

    signed_data = "SSHSIG" + [ namespace, reserved, hash_name, digest.digest(message) ].map { |part| SshReader.pack(part) }.join
    key = OpenSSL::PKey.new_raw_public_key("ED25519", key_blob.byteslice(-32, 32))
    raise Invalid, "it doesn't match the report: the report was changed after it was signed" unless key.verify(nil, raw_signature, signed_data)

    @machine_id = self.class.machine_id_for(key_blob)
  rescue OpenSSL::PKey::PKeyError, ArgumentError
    raise Invalid, "it doesn't match the report: the report was changed after it was signed"
  end

  def self.machine_id_for(key_blob)
    secret = Rails.application.key_generator.generate_key("report machine id from key")
    "key:#{OpenSSL::HMAC.hexdigest("SHA256", secret, key_blob).first(20)}"
  end

  private

  def parse_public_key(text)
    type, encoded, *rest = text.to_s.split(" ")
    raise Invalid, "its public_key isn't an ed25519 key" unless type == KEY_TYPE && encoded && rest.empty?
    blob = Base64.strict_decode64(encoded)
    reader = SshReader.new(blob)
    raise Invalid, "its public_key isn't an ed25519 key" unless reader.string == KEY_TYPE && reader.string.bytesize == 32
    reader.finish!
    blob
  rescue ArgumentError
    raise Invalid, "its public_key isn't an ed25519 key"
  end

  def decode(armored)
    body = ARMOR.match(armored.to_s) or raise Invalid, "it isn't an armored SSH signature"
    Base64.strict_decode64(body[1].delete("\n"))
  rescue ArgumentError
    raise Invalid, "it isn't an armored SSH signature"
  end

  # Reads the SSH wire format: uint32 and length-prefixed strings.
  class SshReader
    def self.pack(bytes) = [ bytes.bytesize ].pack("N") + bytes.b

    def initialize(bytes)
      @bytes = bytes.b
      @at = 0
    end

    def raw(count)
      raise Invalid, "it is cut short" if @at + count > @bytes.bytesize
      @bytes.byteslice(@at, count).tap { @at += count }
    end

    def uint32 = raw(4).unpack1("N")
    def string = raw(uint32)

    def finish!
      raise Invalid, "it has trailing bytes" unless @at == @bytes.bytesize
    end
  end
end
