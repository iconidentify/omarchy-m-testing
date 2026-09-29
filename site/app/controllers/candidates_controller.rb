class CandidatesController < ApplicationController
  def index
    @sets = CandidateSet.all
    @builds = Build.runs(Report.visible.to_a)
  end

  def show
    @set = CandidateSet.find(params[:id]) or raise ActiveRecord::RecordNotFound
    @matched = Report.visible.to_a.select { |report| report.build&.matched_set == @set.name }
  end
end
