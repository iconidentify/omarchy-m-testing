module Api
  module V1
    # POST /api/v1/tester_bindings: omarchy-m-test --sign-in, after the GitHub
    # device flow. The body is signed by the machine's key, like a report,
    # under MachineSignature::TESTER_NAMESPACE:
    #
    #   { "binding_version": 1, "github_token": "...", "signature": { "public_key": ..., "signature": ... } }
    #
    # GitHub confirms the token was issued by this site's OAuth app and names
    # its user; the machine is bound to that handle and the token is revoked.
    # The token is never stored. An allowlisted handle is pinned to the GitHub
    # account that first signs in with it: GitHub hands out renamed handles
    # again, and a new owner of the handle can't sign in as the tester.
    class TesterBindingsController < ActionController::API
      include ClientIp

      VERSION = 1
      MAX_BODY_BYTES = 8.kilobytes
      PER_HOUR = ENV.fetch("SIGN_INS_PER_HOUR", 10).to_i

      rate_limit to: PER_HOUR, within: 1.hour, by: -> { client_ip }, only: :create, store: ReportsController::RATE_LIMITS,
                 with: -> { render json: { error: "Too many sign-ins from your network: at most #{PER_HOUR} an hour. Try again later." }, status: :too_many_requests }

      def create
        return refuse("Tester sign-in isn't set up on this site yet.", :service_unavailable) unless Github.configured?
        # A chunked sign-in's length is its body's (ActionDispatch::Request#content_length).
        return refuse("The sign-in is larger than #{MAX_BODY_BYTES / 1.kilobyte} KiB.", :content_too_large) if request.content_length.to_i > MAX_BODY_BYTES

        payload = JSON.parse(request.raw_post)
        return refuse("The sign-in isn't what omarchy-m-test sends. Update omarchy-m-test and sign in again.") unless well_formed?(payload)

        signature = MachineSignature.verify!(payload, namespace: MachineSignature::TESTER_NAMESPACE)
        identity = Github.client.app_token_user(payload["github_token"])
        Github.client.revoke(payload["github_token"])
        if (listed = Tester.find_by(login: identity.login.downcase)) && !listed.account?(identity.id)
          return refuse("@#{identity.login} is a different GitHub account from the tester the admin added under that handle, so it can't sign in as that tester.", :forbidden)
        end

        TesterBinding.bind!(machine_id: signature.machine_id, identity:)
        listed&.pin!(identity.id)
        tester = listed.present?
        render json: {
          login: identity.login,
          tester:,
          message: if tester
                     "Signed in as @#{identity.login}. This Mac's runs now count as tester runs."
                   else
                     "Signed in as @#{identity.login}, which isn't on the tester allowlist yet. Once the admin adds it, this Mac's runs count as tester runs."
                   end
        }, status: :created
      rescue JSON::ParserError
        refuse("The sign-in is not valid JSON.", :bad_request)
      rescue MachineSignature::Invalid => invalid
        refuse("The sign-in's signature is not valid, so it was refused (#{invalid.message}).")
      rescue Github::Error => error
        refuse("GitHub didn't confirm the sign-in (#{error.message}). Run omarchy-m-test --sign-in again.", :unauthorized)
      end

      private

      def well_formed?(payload)
        payload.is_a?(Hash) && payload.keys.sort == %w[binding_version github_token signature] &&
          payload["binding_version"] == VERSION && payload["github_token"].is_a?(String) && payload["github_token"].match?(/\A[\w.-]{1,255}\z/)
      end

      def refuse(error, status = :unprocessable_content) = render(json: { error: }, status:)
    end
  end
end
