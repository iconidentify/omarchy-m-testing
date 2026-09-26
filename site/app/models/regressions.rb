# Regressions. A feature that fails in a report is a regression only when a
# verified earlier run on the same Mac model (board) and stack passed it: a
# visible tester run (Report#tester?) uploaded before the failing report in
# which the feature worked. Without one the failure stays "fails", so a
# user's setup error, or a feature that never worked on that Mac, isn't taken
# for a regression. The Omarchy version may differ: that's what a regression is.
class Regressions
  # A regression still open: the newest run testing the feature on this model
  # and stack is a regression. reports: its regressed runs, newest first.
  Open = Data.define(:feature_id, :board, :stack, :reports) do
    def feature = Catalogue.feature(feature_id)
    def latest = reports.first
    def pass = latest.regressed_from(feature_id)
    def layer = feature&.fetch("layer")
  end

  # Read once per request.
  def self.current = Current.regressions ||= new(Report.visible.where.not(tester_login: nil).to_a)

  # reports: where verified passes come from; only tester runs count.
  def initialize(reports)
    @passes = {}
    reports.select(&:tester?).sort_by(&:upload_order).each do |report|
      report.tested_states.each do |feature_id, state|
        (@passes[[ report.board, report.stack, feature_id ]] ||= []) << report if state == "works"
      end
    end
  end

  # The latest verified pass of the feature on the report's model and stack
  # uploaded before the report, or nil.
  def pass_before(report, feature_id)
    passes = @passes[[ report.board, report.stack, feature_id ]] or return nil
    passes.reverse_each.find { |pass| (pass.upload_order <=> report.upload_order).negative? }
  end

  # The regressions still open in these reports, by feature and model.
  def self.open(reports)
    runs = Hash.new { |hash, key| hash[key] = [] }
    reports.sort_by(&:upload_order).reverse_each do |report|
      report.feature_states.each do |feature_id, state|
        runs[[ feature_id, report.board, report.stack ]] << [ report, state ] unless state == "not-tested"
      end
    end
    runs.filter_map do |(feature_id, board, stack), states|
      next unless states.first.last == "regression"

      Open.new(feature_id:, board:, stack:, reports: states.take_while { |_report, state| state == "regression" }.map(&:first))
    end.sort_by { |regression| [ Catalogue.feature_name(regression.feature_id), regression.latest.short_model_name, regression.stack ] }
  end
end
