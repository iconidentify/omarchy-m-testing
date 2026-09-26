# The compatibility matrix: one row per Mac model and Omarchy stack/version,
# one cell per catalogue feature some check tests, from the visible reports.
class CompatibilityMatrix
  STACKS = %w[converged mx-mac legacy-omarchy-mac reference].freeze

  Row = Data.define(:configuration, :model_name, :chip, :soc, :reports, :cells) do
    def cell(feature_id) = cells.fetch(feature_id) { MatrixCell.new({}, []) }
  end

  def self.visible(stack: nil)
    scope = Report.visible
    scope = scope.where("body -> 'system' ->> 'stack' = ?", stack) if stack.present?
    new(scope.to_a)
  end

  def initialize(reports)
    @reports = reports.sort_by { |report| [ report.created_at, report.id ] }
  end

  def features = Catalogue.tested_features
  def reports = @reports.reverse
  def empty? = @reports.empty?

  def rows
    @rows ||= @reports.group_by(&:configuration).map do |configuration, reports|
      latest = reports.last
      Row.new(configuration:, model_name: latest.short_model_name, chip: latest.chip, soc: latest.soc, reports: reports.reverse,
              cells: features.to_h { |feature| [ feature.fetch("id"), MatrixCell.from(reports, feature.fetch("id")) ] })
    end.sort { |a, b| compare(a, b) }
  end

  def rows_for_board(board) = rows.select { |row| row.configuration.board == board }

  # Rows with at least one report that tested the feature.
  def rows_for_feature(feature_id) = rows.select { |row| row.cell(feature_id).reports.any? }

  def as_json(*)
    {
      catalogue_version: Catalogue.version,
      agreement: "a cell's state is set once #{MatrixCell::AGREEMENT} or more distinct machines agree; null while unconfirmed",
      features: features.map { |f| { id: f["id"], name: f["name"], layer: f["layer"] } },
      rows: rows.map do |row|
        {
          model: row.model_name, board: row.configuration.board, soc: row.soc, chip: row.chip,
          stack: row.configuration.stack, version: row.configuration.version, reports: row.reports.size,
          cells: row.cells.transform_values { |cell| { state: cell.state, tentative: cell.tentative, machines: cell.tallies } }
        }
      end
    }
  end

  private

  # By chip generation, model and stack; within those, newest version first.
  def compare(a, b)
    order = (sort_key(a) <=> sort_key(b)).to_i
    order.zero? ? version_key(b) <=> version_key(a) : order
  end

  def sort_key(row)
    [ Catalogue.chips.keys.index(Catalogue.chip_for_soc(row.soc)) || Catalogue.chips.size,
      row.model_name, STACKS.index(row.configuration.stack) || STACKS.size ]
  end

  def version_key(row)
    Gem::Version.new(row.configuration.version)
  rescue ArgumentError
    Gem::Version.new("0")
  end
end
