class MatrixController < ApplicationController
  # ?stack= filters by stack, ?build= to the runs on one build, ?group=release merges each release's builds.
  def show
    @stack = params[:stack].presence_in(CompatibilityMatrix::STACKS)
    @build = params[:build].presence
    @by_build = params[:group] != "release"
    @matrix = CompatibilityMatrix.visible(stack: @stack, build: @build, by_build: @by_build)
    @builds = CompatibilityMatrix.builds(stack: @stack)
  end
end
