class CandidatesController < ApplicationController
  def index
    @sets = CandidateSet.all
  end

  def show
    @set = CandidateSet.find(params[:id]) or raise ActiveRecord::RecordNotFound
  end
end
