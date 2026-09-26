class BenchmarksController < ApplicationController
  def show
    @scores = BenchmarkScores.visible
  end
end
