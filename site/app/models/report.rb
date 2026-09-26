# One uploaded report. The body is the schema-validated report exactly as the
# CLI sent it; public_id is the unguessable id in its URL. Only a digest of the
# deletion token is stored; the token itself is returned once, at upload.
#
# machine_id groups reports by machine for the "two or more distinct machines
# agree" rule. Until reports carry a machine key (ticket 09) it is a keyed
# digest of the uploader's IP address: never shown, never exported, and
# conservative (two Macs behind one network count as one machine). Reports
# without one (uploaded before it existed) all count as a single machine.
class Report < ApplicationRecord
  has_secure_token :public_id, length: 24

  attr_reader :deletion_token

  validates :body, :schema_version, presence: true

  before_validation :issue_deletion_token, on: :create

  scope :visible, -> { where(hidden_at: nil) }
  scope :newest_first, -> { order(created_at: :desc, id: :desc) }

  # The packages whose version is "the Omarchy version" of a run, by preference.
  OMARCHY_PACKAGES = %w[omarchy omarchy-dev omarchy-mac].freeze

  STACK_WORDS = {
    "converged" => "converged",
    "mx-mac" => "mx-mac",
    "legacy-omarchy-mac" => "legacy omarchy-mac",
    "reference" => "reference"
  }.freeze

  def self.digest(token)
    OpenSSL::Digest::SHA256.hexdigest(token.to_s)
  end

  # An IPv6 address counts by its /64: a Mac's temporary IPv6 address changes
  # daily, so the full address would make one Mac look like several.
  def self.machine_id_for_ip(ip)
    address = IPAddr.new(ip.to_s)
    network = address.ipv6? && !address.ipv4_mapped? ? address.mask(64).to_s : address.native.to_s
    key = Rails.application.key_generator.generate_key("report machine id from ip")
    "ip:#{OpenSSL::HMAC.hexdigest("SHA256", key, network).first(20)}"
  rescue IPAddr::InvalidAddressError
    "ip:unknown"
  end

  def deletion_token_matches?(token)
    token.present? && ActiveSupport::SecurityUtils.secure_compare(deletion_token_digest, self.class.digest(token))
  end

  def machine = body.fetch("machine")
  def system = body.fetch("system")
  def checks = body.fetch("checks")

  def model_name = machine.fetch("model")
  def short_model_name = model_name.delete_prefix("Apple ")
  def board = machine.fetch("board")
  def soc = machine.fetch("soc")
  def chip = machine.fetch("chip")
  def kernel = machine.fetch("kernel")
  def stack = system.fetch("stack")
  def stack_words = STACK_WORDS.fetch(stack, stack)
  def tool_version = body.dig("tool", "version")
  def candidate_set = system["candidate_set"]

  def package_version(name)
    system.fetch("packages").find { |package| package["name"] == name }&.fetch("version")
  end

  # The release a run is on, coarse enough that two machines on the same
  # release share it: the leading dotted numbers of the Omarchy package
  # ("4.0.0.alpha.quattro.r179...-1" is 4.0.0), or the distro for a reference run.
  def omarchy_version
    return system.fetch("distro") if stack == "reference"

    OMARCHY_PACKAGES.each do |name|
      version = package_version(name) or next
      return version[/\A\d+(\.\d+)*/] || version
    end
    "unknown"
  end

  # Model x stack/version: one row of the compatibility matrix.
  def configuration = Configuration.new(board:, stack:, version: omarchy_version)

  # The machine this report counts as for agreement between machines.
  def machine_key = machine_id || "unknown"

  def hidden? = hidden_at.present?

  # Result per catalogue feature this report tested: feature id => ResultState.
  def feature_states
    @feature_states ||= checks.group_by { |check| check.dig("classification", "feature") }
                              .transform_values { |group| ResultState.combine(group.map { |check| check.dig("classification", "outcome") }) }
  end

  def to_param = public_id

  private

  def issue_deletion_token
    @deletion_token = SecureRandom.urlsafe_base64(32)
    self.deletion_token_digest = self.class.digest(@deletion_token)
  end
end
