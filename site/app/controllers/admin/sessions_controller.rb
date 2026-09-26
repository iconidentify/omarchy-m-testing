module Admin
  class SessionsController < ApplicationController
    rate_limit to: 10, within: 15.minutes, by: -> { client_ip }, only: :create, store: Api::V1::ReportsController::RATE_LIMITS,
               with: -> { render "admin/sessions/new", status: :too_many_requests }

    def create
      raise ActionController::RoutingError, "Not Found" if AdminAuthentication.token.nil?

      if AdminAuthentication.valid?(params[:token])
        reset_session
        sign_in_admin
        redirect_to admin_root_path
      else
        flash.now[:alert] = "That token isn't right."
        render "admin/sessions/new", status: :unauthorized
      end
    end

    def destroy
      reset_session
      redirect_to root_path
    end
  end
end
