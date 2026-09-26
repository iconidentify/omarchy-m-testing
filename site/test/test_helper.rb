ENV["RAILS_ENV"] ||= "test"
require_relative "../config/environment"
require "rails/test_help"

module ActiveSupport
  class TestCase
    parallelize(workers: :number_of_processors)
  end
end

# The golden reports shared with the CLI's Seam A tests (schema/golden/).
module GoldenReports
  def self.paths = Dir[ReportSchema.dir.join("golden", "*.json")].sort
  def self.text(name) = ReportSchema.dir.join("golden", "#{name}.json").read
  def self.json(name) = JSON.parse(text(name))
end
