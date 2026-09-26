# Evidence rules the schema can't express: evidence is text only and at most
# 64 KiB per report. The CLI applies the same rules before it writes a report
# (cli/omarchy_m_test/privacy.py); the site refuses reports that break them.
module ReportEvidence
  MAX_BYTES = 64.kilobytes
  NON_TEXT = /[\x00-\x08\x0a-\x1f\u{fffd}]/

  # Human-readable problems with the report's evidence; empty when it is fine.
  def self.errors(report)
    lines = report.fetch("checks").flat_map { |check| check.fetch("evidence") }
    problems = []
    total = lines.sum(&:bytesize)
    problems << "evidence is #{total} bytes; a report carries at most #{MAX_BYTES}" if total > MAX_BYTES
    lines.each_with_index do |line, index|
      problems << "evidence line #{index + 1} is not text" if line.match?(NON_TEXT)
    end
    problems.first(10)
  end
end
