# The build a run is on, derived from what its report records, the way
# omarchy-m-test derives it (cli/omarchy_m_test/system.py, build_words):
#
#   id       the Omarchy runtime's commit (7 characters, from the omarchy
#            package's ".g<commit>") and its build stamp (the pkgrel suffix the
#            candidate-set lane gives every package of one build, "-1.2026092602"),
#            e.g. "f60e1ba.2026092602"; a release package's own version when it
#            has neither
#   kernel   the linux-aurora version
#   boot     the omarchy-mac-boot version, less the build's stamp
#
# Two runs are on the same build when all three match: the same runtime with a
# kernel installed by hand is a different build to look at. Reference runs
# (another distro) have none. Old reports have everything this needs.
#
# The candidate set is the one the image names (system.candidate_set), else a
# set the site knows was built with exactly this omarchy package
# (config/candidate_sets.yml): matched, shown, but never counted towards the
# set's promotion.
class Build
  RUNTIME_PACKAGES = %w[omarchy omarchy-settings omarchy-dev].freeze
  # system.image's keys in the order the CLI reads them (cli/omarchy_m_test/system.py IMAGE_KEYS); others after, by name.
  IMAGE_KEYS = %w[platform candidate_set candidate_source_commit builder_commit builder_tree_clean image_profile
                  built image_version image_id package_set_sha256].freeze
  COMMIT = /\.g([0-9a-f]{7,40})(?![0-9a-f])/
  STAMP = /-\d+\.(\d+)\z/

  attr_reader :id, :commit, :stamp, :kernel, :boot, :candidate_set, :image, :tool_version

  def self.for(report)
    return if report.stack == "reference"

    packages = report.system.fetch("packages", []).to_h { |package| [ package["name"], package["version"] ] }
    image = report.system["image"].is_a?(Hash) ? report.system["image"] : {}
    image = image.sort_by { |key, _| [ IMAGE_KEYS.index(key) || IMAGE_KEYS.size, key ] }.to_h
    build = new(packages, candidate_set: report.candidate_set || image["candidate_set"], image:, tool_version: report.tool_version)
    build if build.present?
  end

  # The runs on each build, newest build first: [[build, reports newest first], ...]. Reference runs have none.
  def self.runs(reports)
    reports.select(&:build).sort_by(&:upload_order).reverse.group_by { |report| report.build.key }
           .map { |_key, runs| [ runs.first.build, runs ] }
  end

  def initialize(packages, candidate_set: nil, image: {}, tool_version: nil)
    @packages = packages
    runtime = RUNTIME_PACKAGES.filter_map { |name| packages[name] }.first
    @commit = runtime && runtime[COMMIT, 1]&.first(7)
    @stamp = [ *RUNTIME_PACKAGES, "omarchy-mac" ].filter_map { |name| packages[name]&.[](STAMP, 1) }.first
    found = [ @commit, @stamp ].compact.join(".")
    @id = found.presence || [ *RUNTIME_PACKAGES, "omarchy-mac" ].filter_map { |name| packages[name] }.first
    @kernel = packages["linux-aurora"]
    @boot = packages["omarchy-mac-boot"]&.then { |version| @stamp && version.end_with?(".#{@stamp}") ? version.delete_suffix(".#{@stamp}") : version }
    @candidate_set = candidate_set
    @image = image
    @tool_version = tool_version
  end

  def present? = id.present?

  # "f60e1ba.2026092602 (linux-aurora 7.1.12.aurora2-11, omarchy-mac-boot 20260926-1)": the CLI shows the same.
  def words
    extras = { "linux-aurora" => kernel, "omarchy-mac-boot" => boot }.filter_map { |name, version| "#{name} #{version}" if version }
    extras.any? ? "#{id} (#{extras.join(", ")})" : id
  end

  # What two runs share when they're on the same build.
  def key = [ id, kernel, boot ]

  # The known candidate set built with this omarchy package, when the image doesn't name its set.
  def matched_set = candidate_set ? nil : KnownCandidateSets.for_omarchy(@packages["omarchy"])

  def set = candidate_set || matched_set

  # How the set is known: the image names it, or its packages match a known set.
  def set_source
    if candidate_set then "image"
    elsif matched_set then "packages"
    end
  end

  def as_json(*)
    { id:, words:, commit:, stamp:, linux_aurora: kernel, omarchy_mac_boot: boot, candidate_set: set, candidate_set_source: set_source,
      image: image.presence, tool_version: }.compact
  end
end
