# The runs on one candidate set's images (the report's system.candidate_set,
# from the image's target record), and whether the set is ready to promote:
# tester runs only, per Mac model and feature. Community runs on the set are
# listed but don't count.
#
#   waiting  no tester run yet
#   blocked  a tester run found a regression (red: it should work there)
#   ready    tester runs on at least one model, and none found a regression
class CandidateSet
  NAME = /[A-Za-z0-9._-]{1,128}/

  Finding = Data.define(:row, :feature, :cell)

  attr_reader :name, :reports

  def self.all
    Report.visible.where("(body -> 'system' ->> 'candidate_set') IS NOT NULL").to_a
          .group_by(&:candidate_set)
          .map { |name, reports| new(name, reports) }
          .sort_by { |set| [ -set.latest.created_at.to_i, set.name ] }
  end

  def self.find(name)
    reports = Report.visible.where("body -> 'system' ->> 'candidate_set' = ?", name.to_s).to_a
    new(name, reports) if reports.any?
  end

  def initialize(name, reports)
    @name = name
    @reports = reports
  end

  def tester_reports = reports.select(&:tester?)
  def latest = reports.max_by(&:created_at)
  def matrix = @matrix ||= CompatibilityMatrix.new(reports, only_testers: true)
  def rows = matrix.rows
  def features = matrix.features

  # Rows tester runs tested.
  def tested_rows = rows.select { |row| row.cells.values.any?(&:tester?) }

  def findings(state)
    rows.flat_map do |row|
      features.filter_map do |feature|
        cell = row.cell(feature["id"])
        Finding.new(row:, feature:, cell:) if cell.tester? && cell.state == state
      end
    end
  end

  def regressions = findings("regression")
  def partials = findings("partial")

  def verdict
    if tester_reports.empty? then "waiting"
    elsif regressions.any? then "blocked"
    else "ready"
    end
  end

  def verdict_words
    case verdict
    when "waiting" then "Waiting for tester runs"
    when "blocked" then "Not ready: tester runs found #{regressions.size} #{"regression".pluralize(regressions.size)}"
    else "Ready for promotion: tester runs on #{tested_rows.map(&:model_name).uniq.size} #{"model".pluralize(tested_rows.map(&:model_name).uniq.size)}, no regressions"
    end
  end

  def to_param = name
end
