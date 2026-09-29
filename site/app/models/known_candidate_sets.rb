# The candidate sets the site knows by their packages (config/candidate_sets.yml),
# so a run on a set's exact omarchy package maps to the set even when its
# image doesn't name it.
module KnownCandidateSets
  Entry = Data.define(:name, :source_commit, :created, :omarchy)

  def self.all
    @all ||= YAML.safe_load_file(Rails.root.join("config", "candidate_sets.yml")).map do |name, set|
      Entry.new(name:, source_commit: set.fetch("source_commit"), created: set.fetch("created"), omarchy: set.fetch("omarchy"))
    end.freeze
  end

  def self.find(name) = all.find { |set| set.name == name }

  # The set built with exactly this omarchy package version, or nil.
  def self.for_omarchy(version) = version && all.find { |set| set.omarchy == version }&.name
end
