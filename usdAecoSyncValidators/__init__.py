"""Register legacy checks with the native Python UsdValidation plugin API."""
from pxr import UsdValidation
from aeco_sync.validators import bindings, intent_rules
from . import validatorTokens as tokens


def wrap(function):
    def task(stage, time_range):
        return [UsdValidation.ValidationError(error.GetName()[0].upper() + error.GetName()[1:],
                    error.GetType(), error.GetSites(), error.GetMessage())
                for error in function(stage, time_range)]
    return task


registry = UsdValidation.ValidationRegistry()
registry.RegisterPluginStageValidator(tokens.BINDINGS_CHECKER, wrap(bindings))
registry.RegisterPluginStageValidator(tokens.INTENT_CHECKER, wrap(intent_rules))
