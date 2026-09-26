# One feature on one configuration (model x stack/version), aggregated over
# the visible reports. Each machine counts once, with the latest state it
# tested. The cell only takes a colour when two or more distinct machines
# agree; until then it shows the community reports, labelled as unconfirmed.
# Machines agreeing on different states make it partial. Tester runs colour a
# cell on their own once tester sign-in exists (ticket 19).
class MatrixCell
  AGREEMENT = 2

  attr_reader :tallies, :reports

  # reports: oldest first, all on the same configuration.
  def self.from(reports, feature_id)
    latest = {}
    tested = []
    reports.each do |report|
      state = report.feature_states[feature_id]
      next if state.nil? || state == "not-tested"

      tested << report
      latest[report.machine_key] = state
    end
    new(latest.values.tally, tested.reverse)
  end

  def initialize(tallies, reports)
    @tallies = tallies
    @reports = reports
  end

  def machines = tallies.values.sum

  # The colour state, or nil while the community reports don't agree yet.
  def state
    return "not-tested" if tallies.empty?

    agreed = tallies.select { |_state, count| count >= AGREEMENT }.keys
    return agreed.first if agreed.one?

    "partial" if agreed.many?
  end

  def confirmed? = state.present? && tallies.any?
  def unconfirmed? = state.nil?

  # What the community reports say before machines agree.
  def tentative
    tallies.max_by { |state, count| [ count, -ResultState::ORDER.index(state) ] }&.first || "not-tested"
  end

  def display_state = state || tentative

  def css_class
    if unconfirmed? then "cell cell-unconfirmed cell-hint-#{tentative}"
    else "cell cell-#{state}"
    end
  end

  def summary
    if tallies.empty?
      "not tested"
    elsif confirmed?
      "#{ResultState.words(state)}: #{describe_tallies}"
    else
      "community, unconfirmed: #{describe_tallies}; colours once #{AGREEMENT} machines agree"
    end
  end

  private

  def describe_tallies
    tallies.sort_by { |state, _| ResultState::ORDER.index(state) }
           .map { |state, count| "#{count} #{count == 1 ? "machine" : "machines"} #{ResultState.words(state)}" }
           .join(", ")
  end
end
