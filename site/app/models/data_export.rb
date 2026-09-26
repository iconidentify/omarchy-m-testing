# Everything public, for download: visible reports as JSON (each report exactly
# as uploaded), and as CSV one row per report or one row per check result.
# Published under CC0. Deleted and hidden reports are never included, nor is
# the machine grouping key.
module DataExport
  LICENSE = { id: "CC0-1.0", url: "https://creativecommons.org/publicdomain/zero/1.0/" }.freeze
  ASAHI_NOTE = "Expected Asahi states come from the Asahi Linux feature-support tables, CC BY 3.0; see the catalogue's sources."

  REPORT_COLUMNS = %w[
    id url uploaded_at model board soc chip kernel stack omarchy_version distro boot_loader encryption candidate_set
    tool_version schema_version catalogue_version checks pass fail skip
  ].freeze

  CHECK_COLUMNS = %w[
    report_id uploaded_at model board soc chip kernel stack omarchy_version
    check_id kind status outcome feature layer expected_asahi expected_aurora expected_omarchy
    score score_unit score_tool score_suite
  ].freeze

  def self.reports = Report.visible.order(:created_at, :id)

  def self.json(url_for)
    {
      license: LICENSE,
      note: ASAHI_NOTE,
      generated_at: Time.current.utc.iso8601,
      catalogue_version: Catalogue.version,
      reports: reports.map do |report|
        { id: report.public_id, url: url_for.call(report), uploaded_at: report.created_at.utc.iso8601, report: report.body }
      end
    }
  end

  def self.reports_csv(url_for)
    csv(REPORT_COLUMNS, reports.map do |report|
      statuses = report.checks.map { |check| check["status"] }.tally
      [ report.public_id, url_for.call(report), report.created_at.utc.iso8601, report.model_name, report.board, report.soc, report.chip,
        report.kernel, report.stack, report.omarchy_version, report.system["distro"], report.system["boot_loader"],
        report.system["encryption"], report.candidate_set, report.tool_version, report.schema_version, report.body["catalogue_version"],
        report.checks.size, statuses.fetch("pass", 0), statuses.fetch("fail", 0), statuses.fetch("skip", 0) ]
    end)
  end

  def self.checks_csv
    csv(CHECK_COLUMNS, reports.flat_map do |report|
      report.checks.map do |check|
        classification = check["classification"]
        [ report.public_id, report.created_at.utc.iso8601, report.model_name, report.board, report.soc, report.chip, report.kernel,
          report.stack, report.omarchy_version, check["id"], check["kind"], check["status"], classification["outcome"],
          classification["feature"], classification["layer"], *Catalogue::LAYERS.map { |layer| classification.dig("expected", layer) },
          *%w[value unit tool suite].map { |field| check.dig("score", field) } ]
      end
    end)
  end

  # RFC 4180: every field quoted, quotes doubled, CRLF line ends. Uploaded
  # text starting like a formula gets a leading ' so spreadsheets show it as text.
  def self.csv(header, rows)
    [ header, *rows ].map { |row| row.map { |field| %("#{defuse(field.to_s).gsub('"', '""')}") }.join(",") + "\r\n" }.join
  end

  def self.defuse(text) = text.match?(/\A[=+\-@\t\r]/) ? "'#{text}" : text
end
