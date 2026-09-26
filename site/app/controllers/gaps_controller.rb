class GapsController < ApplicationController
  def show
    reports = Report.visible.to_a
    @gaps = KernelGaps.new(reports)
    @regressions = Regressions.open(reports)
  end
end
