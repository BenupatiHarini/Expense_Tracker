"""Train a U-Net landslide segmentation model.

Dataset layout (e.g. Bijie Landslide Dataset or your own labelled images):
  data/images/xxx.png   data/masks/xxx.png   (mask: white = landslide, black = background)

Run:  python train.py --data data --epochs 30
Output: weights/unet.pth  (app.py loads it automatically)
"""
import argparse, glob, os
import cv2, numpy as np, torch
import segmentation_models_pytorch as smp
from torch.utils.data import Dataset, DataLoader, random_split

class DS(Dataset):
    def __init__(self, root, size=512, train=True):
        self.imgs = sorted(glob.glob(os.path.join(root, "images", "*")))
        self.root, self.size, self.train = root, size, train
    def __len__(self): return len(self.imgs)
    def __getitem__(self, i):
        p = self.imgs[i]
        img = cv2.cvtColor(cv2.resize(cv2.imread(p), (self.size, self.size)), cv2.COLOR_BGR2RGB)
        m = cv2.resize(cv2.imread(os.path.join(self.root, "masks", os.path.basename(p)), 0), (self.size, self.size))
        if self.train and np.random.rand() < 0.5: img, m = img[:, ::-1], m[:, ::-1]
        img = (img.astype(np.float32) / 255 - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
        return (torch.from_numpy(img.transpose(2, 0, 1).copy()).float(),
                torch.from_numpy((m > 127).astype(np.float32).copy())[None])

def iou(logits, y):
    p = (torch.sigmoid(logits) > 0.5).float()
    return ((p * y).sum() / ((p + y).clamp(0, 1).sum() + 1e-6)).item()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data"); ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--bs", type=int, default=8); ap.add_argument("--lr", type=float, default=1e-4)
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    full = DS(a.data); n_val = max(1, int(0.2 * len(full)))
    tr, va = random_split(full, [len(full) - n_val, n_val], generator=torch.Generator().manual_seed(1))
    tl, vl = DataLoader(tr, a.bs, shuffle=True), DataLoader(va, a.bs)
    model = smp.Unet("resnet34", encoder_weights="imagenet", in_channels=3, classes=1).to(dev)
    loss_fn = lambda o, y: smp.losses.DiceLoss("binary")(o, y) + torch.nn.BCEWithLogitsLoss()(o, y)
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)
    best = 0
    os.makedirs("weights", exist_ok=True)
    for ep in range(a.epochs):
        model.train()
        for x, y in tl:
            x, y = x.to(dev), y.to(dev); opt.zero_grad(); loss_fn(model(x), y).backward(); opt.step()
        model.eval(); s = []
        with torch.no_grad():
            for x, y in vl: s.append(iou(model(x.to(dev)), y.to(dev)))
        m = float(np.mean(s)); print(f"epoch {ep+1}/{a.epochs}  val IoU {m:.3f}")
        if m > best: best = m; torch.save(model.state_dict(), "weights/unet.pth")
    print("best val IoU:", round(best, 3))
