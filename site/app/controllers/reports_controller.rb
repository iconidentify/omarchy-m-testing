class ReportsController < ApplicationController
  before_action :set_report, except: :index
  before_action :require_deletion_token, only: %i[deletion destroy]

  # The runs the filters (ReportFilter) pass: ?build= lists the runs on one build (Build#matches?).
  def index
    @filter = ReportFilter.new(params, keys: ReportFilter::LIST_KEYS)
    all = Report.visible.newest_first.to_a
    @reports = @filter.runs(all)
    @options = FilterOptions.new(all)
  end

  def show
    raise ActiveRecord::RecordNotFound if @report.hidden? && !admin?
  end

  def deletion
  end

  # Deletes the row, and with it the report body and all its evidence.
  def destroy
    @report.destroy!
    render :deleted
  end

  private

  def set_report
    @report = Report.find_by!(public_id: params[:id])
  end

  def require_deletion_token
    raise ActiveRecord::RecordNotFound unless @report.deletion_token_matches?(params[:token])
  end
end
