class MatrixController < ApplicationController
  # The filters (ReportFilter) take ?stack=, ?build= and the rest; ?group=release merges each release's builds.
  def show
    @filter = ReportFilter.new(params)
    @stack = @filter["stack"]
    @build = @filter["build"]
    @by_build = params[:group] != "release"
    @matrix = CompatibilityMatrix.visible(by_build: @by_build, filter: @filter)
    @builds = CompatibilityMatrix.builds(filter: @filter)
    @options = FilterOptions.new(Report.visible.to_a)
  end
end
