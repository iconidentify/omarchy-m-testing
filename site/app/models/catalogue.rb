# The feature catalogue shared with the CLI (../catalogue/catalogue.json from
# the repo root, or CATALOGUE_PATH when the site is deployed without the rest
# of the repo). The site knows a check id only if the catalogue does, and
# words each classification outcome the way the CLI does.
module Catalogue
  def self.path
    Pathname(ENV.fetch("CATALOGUE_PATH") { Rails.root.join("..", "catalogue", "catalogue.json").to_s })
  end

  def self.data
    @data ||= JSON.parse(path.read)
  end

  def self.version = data.fetch("catalogue_version")
  def self.check_ids = data.fetch("checks").keys
  def self.outcome_words(outcome) = data.fetch("outcomes").fetch(outcome, outcome)
  def self.asahi_credit = data.dig("sources", "asahi", "credit")

  def self.feature(id)
    @features ||= data.fetch("features").index_by { |f| f.fetch("id") }
    @features[id]
  end

  # Check ids in the report that this catalogue doesn't know.
  def self.unknown_check_ids(report)
    Array(report["checks"]).filter_map { |check| check["id"] }.uniq - check_ids
  end
end
