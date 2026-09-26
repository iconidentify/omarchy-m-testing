class ReportsController < ApplicationController
  before_action :set_report
  before_action :require_deletion_token, only: %i[deletion destroy]

  def show
  end

  def deletion
  end

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
