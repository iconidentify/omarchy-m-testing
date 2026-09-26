Rails.application.routes.draw do
  namespace :api do
    namespace :v1 do
      resources :reports, only: :create
    end
  end

  resources :reports, only: %i[show destroy] do
    get :deletion, on: :member
  end

  get "up" => "rails/health#show", as: :rails_health_check
end
