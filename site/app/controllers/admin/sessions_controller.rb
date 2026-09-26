module Admin
  class SessionsController < ApplicationController
    rate_limit to: 10, within: 15.minutes, by: -> { client_ip }, only: %i[create callback], store: Api::V1::ReportsController::RATE_LIMITS,
               with: -> { render "admin/sessions/new", status: :too_many_requests }

    # Off to GitHub (or, before GitHub sign-in is set up, the ADMIN_TOKEN).
    def create
      if AdminAuthentication.github?
        session[:github_state] = state = SecureRandom.urlsafe_base64(24)
        redirect_to Github.authorize_url(redirect_uri: auth_github_callback_url, state:), allow_other_host: true
      elsif AdminAuthentication.token
        if AdminAuthentication.valid?(params[:token])
          sign_in_admin
          redirect_to admin_root_path
        else
          refuse "That token isn't right."
        end
      else
        raise ActionController::RoutingError, "Not Found"
      end
    end

    # GitHub sends the admin back here with a code.
    def callback
      raise ActionController::RoutingError, "Not Found" unless AdminAuthentication.github?

      expected = session.delete(:github_state)
      return refuse("That sign-in link is stale. Sign in again.") unless expected.present? && params[:state].is_a?(String) &&
                                                                     ActiveSupport::SecurityUtils.secure_compare(expected, params[:state])
      return refuse("GitHub didn't sign you in.") unless params[:code].is_a?(String) && params[:code].present?

      token = Github.client.exchange_code(code: params[:code], redirect_uri: auth_github_callback_url)
      identity = Github.client.user(token)
      return refuse("@#{identity.login} isn't an admin of this site.") unless AdminAuthentication.admin_login?(identity.login)

      sign_in_admin(login: identity.login)
      redirect_to admin_root_path
    rescue Github::Error => error
      refuse "GitHub didn't sign you in (#{error.message})."
    end

    def destroy
      reset_session
      redirect_to root_path
    end

    private

    def refuse(message)
      flash.now[:alert] = message
      render "admin/sessions/new", status: :unauthorized
    end
  end
end
