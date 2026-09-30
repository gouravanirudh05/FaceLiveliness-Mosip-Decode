package io.mosip.extensions.liveness.desktopui;

import io.mosip.extensions.liveness.api.ActiveChallenge;

/**
 * UI boundary for a later JavaFX companion window. It stays separate from
 * MOSIP FXML because the Registration Client repository is not modified.
 */
public interface ChallengePresenter {
    void show(ActiveChallenge challenge);
    void clear();
}
