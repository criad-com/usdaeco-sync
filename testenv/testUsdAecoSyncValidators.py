#!/pxrpythonsubst
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from aeco_sync import register_plugins
register_plugins()
from pxr import Plug, Sdf, Usd, UsdValidation, Gf
from aeco_sync.stack import create, PREFIX
from aeco_sync.edits import author
Plug.Registry().RegisterPlugins(str(ROOT / "usdAecoSyncValidators"))

class TestValidators(unittest.TestCase):
    def check_error(self, error, rule, stage):
        validator = UsdValidation.ValidationRegistry().GetOrLoadValidatorByName("usdAecoSyncValidators:" + rule + "Checker")
        self.assertIn(error, [e.GetName() for e in validator.Validate(stage)])

    def test_BindingMissing(self):
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/Wall", "Xform")
        prim.ApplyAPI("AecoAxisAPI")
        self.check_error("BindingMissing", "Bindings", stage)

    def test_BindingInstanceUnregistered(self):
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/Wall", "Xform").ApplyAPI("AecoHostBindingAPI", "unknown")
        self.check_error("BindingInstanceUnregistered", "Bindings", stage)

    def session_case(self, error):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = Usd.Stage.CreateNew(str(root / "model.usda"))
            prim = stage.DefinePrim("/Wall", "Xform")
            prim.ApplyAPI("AecoAxisAPI")
            prim.GetAttribute("aeco:axis:end").Set(Gf.Vec3d(0,0,2))
            stage.GetRootLayer().Save()
            document = root / "native.txt"
            document.write_text("document")
            session = create(root / "model.usda", document)
            author(session, "/Wall", ["length=3"])
            if error == "DerivedAuthoredInIntent":
                with Usd.EditContext(session.stage, session.intent):
                    session.stage.GetAttributeAtPath("/Wall.aeco:axis:length").Set(10)
            else:
                session.layer("result.ifc.usda").customLayerData = {PREFIX + "version": "changed"}
            self.check_error(error, "Intent", session.stage)

    def test_DerivedAuthoredInIntent(self): self.session_case("DerivedAuthoredInIntent")
    def test_StaleIntent(self): self.session_case("StaleIntent")

if __name__ == "__main__": unittest.main()
