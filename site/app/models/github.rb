# The site's side of the GitHub OAuth app (omarchy-m-testing, owned by the
# site's owner): GITHUB_CLIENT_ID and the secret GITHUB_CLIENT_SECRET.
#
# - Admin sign-in: the web flow (authorize_url, then exchange_code and user).
# - Tester binding: the CLI signs in with the device flow, which needs only
#   the client ID, and hands the site the token once; app_token_user checks it
#   was issued by this app and names its user, then the site revokes it.
#
# Github.client is swapped for a fake in tests.
module Github
  class Error < StandardError; end

  Identity = Data.define(:login, :id)

  WEB = "https://github.com"
  API = "https://api.github.com"
  TIMEOUT_SECONDS = 10

  class << self
    attr_writer :client

    def client = @client ||= HttpClient.new
  end

  def self.client_id = ENV["GITHUB_CLIENT_ID"].presence
  def self.client_secret = ENV["GITHUB_CLIENT_SECRET"].presence
  def self.configured? = client_id.present? && client_secret.present?

  def self.authorize_url(redirect_uri:, state:)
    "#{WEB}/login/oauth/authorize?" + { client_id:, redirect_uri:, state:, scope: "", allow_signup: "false" }.to_query
  end

  class HttpClient
    # The web flow's code for a token.
    def exchange_code(code:, redirect_uri:)
      body = request(:post, "#{WEB}/login/oauth/access_token",
                     form: { client_id: Github.client_id, client_secret: Github.client_secret, code:, redirect_uri: })
      body["access_token"].presence or raise Error, body["error_description"].presence || "GitHub didn't sign you in"
    end

    # Who a token belongs to.
    def user(token) = identity(request(:get, "#{API}/user", bearer: token))

    # Who a token belongs to, only if this app issued it.
    def app_token_user(token)
      identity(request(:post, "#{API}/applications/#{Github.client_id}/token", app: true, json: { access_token: token })["user"])
    end

    def revoke(token)
      request(:delete, "#{API}/applications/#{Github.client_id}/token", app: true, json: { access_token: token })
    rescue Error
      nil # it expires anyway
    end

    private

    def identity(user)
      raise Error, "GitHub didn't say who signed in" unless user.is_a?(Hash) && user["login"].is_a?(String) && user["id"].is_a?(Integer)

      Identity.new(login: user["login"], id: user["id"])
    end

    def request(method, url, form: nil, json: nil, bearer: nil, app: false)
      uri = URI(url)
      request = { post: Net::HTTP::Post, get: Net::HTTP::Get, delete: Net::HTTP::Delete }.fetch(method).new(uri)
      request["Accept"] = "application/json"
      request["User-Agent"] = "omarchy-m-testing.org"
      request["X-GitHub-Api-Version"] = "2022-11-28" if uri.host == URI(API).host
      request["Authorization"] = "Bearer #{bearer}" if bearer
      request.basic_auth(Github.client_id, Github.client_secret) if app
      request.set_form_data(form) if form
      if json
        request["Content-Type"] = "application/json"
        request.body = json.to_json
      end
      response = Net::HTTP.start(uri.host, uri.port, use_ssl: true, open_timeout: TIMEOUT_SECONDS, read_timeout: TIMEOUT_SECONDS) do |http|
        http.request(request)
      end
      raise Error, "GitHub answered HTTP #{response.code}" unless response.is_a?(Net::HTTPSuccess)

      response.body.present? ? JSON.parse(response.body) : {}
    rescue JSON::ParserError
      raise Error, "GitHub's answer wasn't JSON"
    rescue SocketError, SystemCallError, IOError, Timeout::Error, OpenSSL::SSL::SSLError, Net::HTTPBadResponse => error
      raise Error, "couldn't reach GitHub (#{error.class})"
    end
  end
end
