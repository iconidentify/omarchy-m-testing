# The choices the filter bar offers (ReportFilter), from the visible runs:
# each a list of [value, words], newest or in the catalogue's order.
class FilterOptions
  def initialize(reports)
    @reports = reports
  end

  def build = Build.runs(@reports).map { |build, runs| [ build.words, "#{build.label} (#{runs.size})" ] }.uniq(&:first)
  def set = values { |report| report.build&.set }.sort.reverse.map { |name| [ name, name ] }
  def release = versions(values(&:omarchy_version))
  def stack = CompatibilityMatrix::STACKS.map { |stack| [ stack, Report::STACK_WORDS.fetch(stack) ] }
  def model = @reports.map { |report| [ report.board, "#{report.short_model_name} (#{report.board})" ] }.uniq(&:first).sort_by(&:last)
  def gen = (ReportFilter.generations & values { |report| Catalogue.chip_for_soc(report.soc)&.split("-")&.first }).map { |gen| [ gen, gen.upcase ] }
  def chip = values(&:chip).sort.map { |chip| [ chip, chip ] }
  def soc = values(&:soc).sort.map { |soc| [ soc, soc ] }
  def runs = [ [ "tester", "tester runs only" ], [ "community", "community runs only" ] ]
  def tool = versions(values(&:tool_version))
  def layer = Catalogue::LAYERS.map { |layer| [ layer, Catalogue::LAYER_WORDS.fetch(layer) ] }
  def state = ReportFilter::STATE_WORDS.to_a

  private

  def values(&block) = @reports.filter_map(&block).uniq

  def versions(list)
    list.sort_by { |version| Gem::Version.correct?(version) ? Gem::Version.new(version) : Gem::Version.new("0") }.reverse.map { |v| [ v, v ] }
  end
end
