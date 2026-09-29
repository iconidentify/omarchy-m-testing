# The shared report schema (../schema/report-v1.schema.json from the repo root,
# or REPORT_SCHEMA_DIR when the site is deployed without the rest of the repo).
module ReportSchema
  VERSION = 1

  def self.dir
    Pathname(ENV.fetch("REPORT_SCHEMA_DIR") { Rails.root.join("..", "schema").to_s })
  end

  def self.schemer
    # ECMA-262 patterns, as the schema's dialect means them: "$" ends the string, so a
    # pattern-checked field can't carry a second line (Ruby's "$" would end the first).
    @schemer ||= JSONSchemer.schema(dir.join("report-v#{VERSION}.schema.json"), regexp_resolver: "ecma")
  end

  # Human-readable problems with the report; empty when it is valid.
  def self.errors(report)
    schemer.validate(report).map { |error| error.fetch("error") }
  end
end
