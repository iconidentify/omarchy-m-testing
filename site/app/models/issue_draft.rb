# A prefilled GitHub "new issue" link for a failure or a gap, which the admin
# opens and files by hand: the site never writes to GitHub. The target is the
# project that owns the finding's layer: Asahi hardware and Aurora additions
# go to the Aurora kernel (omacom/linux), Omarchy integration to
# omacom/omarchy-mac. The body links the reports behind the finding (visible
# ones only, since a hidden report's link doesn't open) and, for a single
# check, its evidence, cut short so the link stays within what GitHub takes.
class IssueDraft
  REPOS = { "asahi" => "omacom/linux", "aurora" => "omacom/linux", "omarchy" => "omacom/omarchy-mac" }.freeze
  KERNEL_REPO = "omacom/linux".freeze
  MAX_BODY = 5000
  MAX_REPORTS = 10
  MAX_EVIDENCE_LINES = 20
  GAP_OUTCOMES = %w[fails not-in-aurora not-in-asahi not-in-omarchy unknown-hardware].freeze

  attr_reader :repo, :title, :body

  def self.repo_for(layer) = REPOS.fetch(layer.to_s, KERNEL_REPO)

  # Whether a check result is a failure or gap worth an issue.
  def self.check?(check) = GAP_OUTCOMES.include?(check.dig("classification", "outcome"))

  # url_for: ->(report) { the report's absolute link }.
  def self.for_check(report, check, url_for:)
    classification = check.fetch("classification")
    feature_id = classification["feature"]
    regressed_from = report.regression?(feature_id) ? report.regressed_from(feature_id) : nil
    outcome = classification["outcome"]
    title = if regressed_from then "Regression: #{Catalogue.feature_name(feature_id)} · #{on(report)}"
    else "#{Catalogue.feature_name(feature_id)}: #{Catalogue.outcome_words(outcome)} · #{on(report)}"
    end
    lines = [
      "`#{check["id"]}` on #{mac(report)}: **#{Catalogue.outcome_words(outcome)}**#{" (a regression)" if regressed_from}.",
      "",
      *feature_lines(feature_id, classification["layer"]),
      *system_lines(report),
      expected_line(classification["expected"]),
      "",
      "Report: #{url_for.call(report)}",
      ("Last verified pass on the same model and stack: #{url_for.call(regressed_from)} (#{regressed_from.omarchy_version})" if regressed_from),
      *evidence_lines(check["evidence"])
    ]
    new(layer: classification["layer"], title:, lines:)
  end

  # A regression still open (Regressions::Open).
  def self.for_regression(regression, url_for:)
    latest = regression.latest
    lines = [
      "#{Catalogue.feature_name(regression.feature_id)} stopped working on #{mac(latest)}: a tester's earlier run on the same model and stack found it working.",
      "",
      *feature_lines(regression.feature_id, regression.layer),
      *system_lines(latest),
      "",
      "Last verified pass: #{url_for.call(regression.pass)} (#{regression.pass.stack_words} #{regression.pass.omarchy_version}, kernel #{regression.pass.kernel})",
      *report_lines("Runs with the regression", regression.reports, url_for)
    ]
    new(layer: regression.layer, title: "Regression: #{Catalogue.feature_name(regression.feature_id)} · #{on(latest)}", lines:)
  end

  # A gap found on real Macs (KernelGaps::ReportedGap).
  def self.for_reported_gap(gap, url_for:)
    layer = Catalogue.feature(gap.feature_id)&.fetch("layer")
    lines = [
      "#{Catalogue.feature_name(gap.feature_id)} is #{Catalogue.outcome_words(gap.outcome)} on the #{gap.chip} (#{gap.soc}), " \
      "found by #{gap.machines} #{"machine".pluralize(gap.machines)}: #{gap.models.join(", ")}.",
      "",
      *feature_lines(gap.feature_id, layer),
      *report_lines("Reports", gap.reports, url_for)
    ]
    new(layer:, title: "#{Catalogue.feature_name(gap.feature_id)}: #{Catalogue.outcome_words(gap.outcome)} on #{gap.chip}", lines:)
  end

  # Hardware no driver claimed (KernelGaps::UnclaimedHardware): the kernel's to claim.
  def self.for_unclaimed(hardware, url_for:)
    chips = hardware.chips.map { |chip, soc| "#{chip} (#{soc})" }.join(", ")
    what = hardware.feature_id ? "#{Catalogue.feature_name(hardware.feature_id)}: #{Catalogue.outcome_words(hardware.outcome)}" : Catalogue.outcome_words(hardware.outcome.to_s)
    lines = [
      "No driver claims the enabled device-tree node `#{hardware.compatible}` on #{chips}, " \
      "found by #{hardware.machines} #{"machine".pluralize(hardware.machines)}: #{hardware.models.join(", ")}.",
      "",
      "Feature catalogue: #{what}.",
      *report_lines("Reports", hardware.reports, url_for)
    ]
    new(layer: "aurora", title: "No driver claims #{hardware.compatible} on #{hardware.chips.map(&:first).uniq.join(", ")}", lines:)
  end

  # A catalogue gap (KernelGaps::CatalogueGap): kind is :missing (Aurora lacks
  # what Asahi supports) or :unverified (Aurora not qualified on it yet).
  def self.for_catalogue_gap(gap, kind:, feature_url:)
    chips = gap.chips.map { |chip| Catalogue.chip_name(chip) }.join(", ")
    name = gap.feature.fetch("name")
    title, first = if kind == :missing
      [ "#{name}: supported by Asahi, not yet by Aurora (#{chips})", "Asahi supports #{name} on #{chips}; the feature catalogue lists it as unsupported in Aurora." ]
    else
      [ "#{name}: verify Aurora on #{chips}", "Asahi supports #{name} on #{chips}; Aurora hasn't been qualified on it there yet." ]
    end
    lines = [ first, "", *feature_lines(gap.feature.fetch("id"), gap.feature.fetch("layer")), "Feature page: #{feature_url}" ]
    new(layer: gap.feature.fetch("layer"), title:, lines:)
  end

  def initialize(layer:, title:, lines:)
    @repo = self.class.repo_for(layer)
    @title = title
    body = [ *lines.compact, "", "From omarchy-m-testing.org, feature catalogue v#{Catalogue.version}." ].join("\n")
    if body.size > MAX_BODY
      body = body.first(MAX_BODY)
      body += "\n```" if body.scan("```").size.odd?
      body += "\n\n(cut short; the linked reports have the rest)"
    end
    @body = body
  end

  def url = "https://github.com/#{repo}/issues/new?#{URI.encode_www_form(title:, body:)}"

  def self.on(report) = "#{report.short_model_name}, #{report.stack_words} #{report.omarchy_version}"
  def self.mac(report) = "#{report.model_name}, #{report.chip} (#{report.soc}, board #{report.board})"

  def self.feature_lines(feature_id, layer)
    [ "- Feature: #{Catalogue.feature_name(feature_id)} (`#{feature_id}`), #{Catalogue::LAYER_WORDS.fetch(layer.to_s, layer)} layer" ]
  end

  def self.system_lines(report)
    [
      "- Stack: #{report.stack_words} #{report.omarchy_version}#{", candidate set #{report.candidate_set}" if report.candidate_set}",
      "- Kernel: #{report.kernel}#{", linux-aurora #{report.aurora_version}" if report.aurora_version}"
    ]
  end

  def self.expected_line(expected)
    return nil unless expected.is_a?(Hash) && expected.any?

    "- Expected: #{expected.map { |layer, status| "#{layer} #{status}" }.join(", ")}"
  end

  def self.report_lines(heading, reports, url_for)
    shown = reports.first(MAX_REPORTS)
    [ "", "#{heading}:", *shown.map { |report| "- #{url_for.call(report)} (#{report.stack_words} #{report.omarchy_version}, #{report.created_at.utc.strftime("%Y-%m-%d")})" },
      ("- and #{reports.size - shown.size} more" if reports.size > shown.size) ]
  end

  def self.evidence_lines(evidence)
    lines = Array(evidence).first(MAX_EVIDENCE_LINES).map { |line| line.to_s.gsub("```", "'''") }
    return [] if lines.empty?

    [ "", "Evidence:", "```text", *lines, ("(#{evidence.size - lines.size} more lines in the report)" if evidence.size > lines.size), "```" ]
  end
end
