# One feature on one configuration (model x stack/version), aggregated over
# the visible reports. Each machine counts once, with the latest state it
# tested. Tester runs (Report#tester?) colour the cell on their own: the state
# the tester machines agree on, partial when they disagree. Without tester
# runs, the cell only takes a colour when two or more distinct machines agree;
# until then it shows the community reports, labelled as unconfirmed.
# Machines agreeing on different states make it partial.
class MatrixCell
  AGREEMENT = 2

  attr_reader :tallies, :tester_tallies, :reports

  # reports: oldest first, all on the same configuration. only_testers: count tester runs only.
  def self.from(reports, feature_id, only_testers: false)
    latest = {} # machine => [state, tester run?], from its latest report that tested the feature
    tested = []
    reports.each do |report|
      tester = report.tester?
      next if only_testers && !tester

      state = report.feature_states[feature_id]
      next if state.nil? || state == "not-tested"

      tested << report
      latest[report.machine_key] = [ state, tester ]
    end
    new(latest.values.map(&:first).tally, tested.reverse, latest.values.select(&:last).map(&:first).tally)
  end

  def initialize(tallies, reports, tester_tallies = {}, hidden: false)
    @tallies = tallies
    @reports = reports
    @tester_tallies = tester_tallies
    @hidden = hidden
  end

  # Hidden by the confirmed-only filter (ReportFilter): what community machines don't agree on yet.
  def hidden? = @hidden

  # This cell with confirmed results only: an unconfirmed one is hidden.
  def confirmed_only = unconfirmed? ? MatrixCell.new({}, [], hidden: true) : self

  def machines = tallies.values.sum
  def tester_machines = tester_tallies.values.sum
  def tester? = tester_tallies.any?

  # The colour state, or nil while the community reports don't agree yet.
  def state
    return if hidden?
    return "not-tested" if tallies.empty?
    return (tester_tallies.one? ? tester_tallies.keys.first : "partial") if tester?

    agreed = tallies.select { |_state, count| count >= AGREEMENT }.keys
    return agreed.first if agreed.one?

    "partial" if agreed.many?
  end

  def confirmed? = state.present? && tallies.any?
  def unconfirmed? = state.nil?

  # What the community reports say before machines agree; partial on a tie.
  def tentative
    return "not-tested" if tallies.empty?

    leaders = tallies.select { |_state, count| count == tallies.values.max }.keys
    leaders.one? ? leaders.first : "partial"
  end

  def display_state = state || tentative

  def css_class
    if hidden? then "cell cell-not-tested cell-hidden"
    elsif unconfirmed? then "cell cell-unconfirmed cell-hint-#{tentative}"
    elsif tester? then "cell cell-#{state} cell-tester"
    else "cell cell-#{state}"
    end
  end

  def summary
    if hidden?
      "unconfirmed community results, hidden (confirmed only)"
    elsif tallies.empty?
      "not tested"
    elsif tester?
      "#{ResultState.words(state)}: tester-verified, #{describe(tester_tallies, "tester machine")}" +
        (machines > tester_machines ? "; #{machines} machines in all" : "")
    elsif confirmed?
      "#{ResultState.words(state)}: #{describe(tallies, "machine")}"
    else
      "community, unconfirmed: #{describe(tallies, "machine")}; colours once #{AGREEMENT} machines agree or a tester confirms"
    end
  end

  private

  def describe(tallies, noun)
    tallies.sort_by { |state, _| ResultState::ORDER.index(state) }
           .map { |state, count| "#{count} #{count == 1 ? noun : noun.pluralize} #{ResultState.words(state)}" }
           .join(", ")
  end
end
