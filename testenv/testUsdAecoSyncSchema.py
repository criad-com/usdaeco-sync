#!/pxrpythonsubst
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from aeco_sync import register_plugins
register_plugins()
from pxr import Plug, Usd, UsdGeom
Plug.Registry().RegisterPlugins(str(ROOT / "usdAecoSync"))

class TestSchema(unittest.TestCase):
    def test_binding_and_diagnostic(self):
        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Xform.Define(stage, "/Wall").GetPrim()
        self.assertTrue(prim.CanApplyAPI("AecoHostBindingAPI", "ifc"))
        prim.ApplyAPI("AecoHostBindingAPI", "ifc")
        prim.ApplyAPI("AecoHostBindingAPI", "revit")
        self.assertTrue(prim.GetAttribute("aeco:host:ifc:ref"))
        self.assertTrue(prim.GetAttribute("aeco:host:revit:ref"))
        diag = stage.DefinePrim("/Finding", "AecoSyncDiagnostic")
        self.assertEqual(diag.GetAttribute("aeco:diag:severity").Get(), "warning")

if __name__ == "__main__": unittest.main()
