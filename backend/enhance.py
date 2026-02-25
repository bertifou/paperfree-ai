"""
enhance.py — Prétraitement d'image pour documents photographiés.

Pipeline :
  1. Deskew        : corrige l'inclinaison du texte
  2. Déperspective : redresse un document photographié en biais (si détecté)
  3. CLAHE         : améliore le contraste local (zones sombres / surexposées)
  4. Débruitage    : réduit le grain photographique

L'image produite est en couleur (pas binarisée) pour que le PDF garde
l'aspect visuel du document original tout en étant bien lisible.
"""

import os
import logging
import tempfile
import numpy as np

logger = logging.getLogger(__name__)


def enhance_image(image_path: str, output_dir: str | None = None) -> str:
    """
    Applique le pipeline complet de mise au point sur l'image.
    Retourne le chemin de l'image améliorée (fichier PNG temporaire ou dans output_dir).
    En cas d'échec, retourne image_path inchangé.
    """
    try:
        import cv2

        img = cv2.imread(image_path)
        if img is None:
            logger.warning(f"[enhance] Impossible de lire : {image_path}")
            return image_path

        logger.info(f"[enhance] Début prétraitement : {os.path.basename(image_path)}")

        img = _correct_perspective(img)
        img = _deskew(img)
        img = _enhance_contrast(img)
        img = _denoise(img)

        # Destination
        base = os.path.splitext(os.path.basename(image_path))[0]
        if output_dir:
            out_path = os.path.join(output_dir, base + "_enhanced.png")
        else:
            # Fichier temporaire persistant (sera nettoyé par l'appelant si besoin)
            tmp = tempfile.NamedTemporaryFile(
                suffix="_enhanced.png", delete=False, dir=output_dir
            )
            out_path = tmp.name
            tmp.close()

        cv2.imwrite(out_path, img)
        logger.info(f"[enhance] Image améliorée sauvegardée : {out_path}")
        return out_path

    except Exception as e:
        logger.error(f"[enhance] Erreur prétraitement, image originale conservée : {e}")
        return image_path


# ---------------------------------------------------------------------------
# Étape 1 — Déperspective
# ---------------------------------------------------------------------------

def _correct_perspective(img: "np.ndarray") -> "np.ndarray":
    """
    Détecte le contour du document dans l'image et redresse la perspective.
    Si aucun quadrilatère clair n'est trouvé, retourne l'image inchangée.
    """
    import cv2

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)

    # Dilater les bords pour connecter les contours
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dilated = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img

    # Garder le plus grand contour
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    doc_contour = None

    for cnt in contours[:5]:
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        area = cv2.contourArea(cnt)

        # On cherche un quadrilatère qui occupe au moins 20 % de l'image
        if len(approx) == 4 and area > 0.20 * h * w:
            doc_contour = approx
            break

    if doc_contour is None:
        logger.debug("[enhance] Déperspective : aucun contour document trouvé")
        return img

    pts = doc_contour.reshape(4, 2).astype(np.float32)
    pts = _order_points(pts)
    tl, tr, br, bl = pts

    # Dimensions cible
    width  = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))

    if width < 100 or height < 100:
        return img

    dst = np.array([[0, 0], [width - 1, 0],
                    [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(pts, dst)
    warped = cv2.warpPerspective(img, M, (width, height))
    logger.info(f"[enhance] Déperspective appliquée → {width}×{height}")
    return warped


def _order_points(pts: "np.ndarray") -> "np.ndarray":
    """Ordonne 4 points : top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # top-left
    rect[2] = pts[np.argmax(s)]   # bottom-right
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right
    rect[3] = pts[np.argmax(diff)]  # bottom-left
    return rect


# ---------------------------------------------------------------------------
# Étape 2 — Deskew (correction d'inclinaison)
# ---------------------------------------------------------------------------

def _deskew(img: "np.ndarray") -> "np.ndarray":
    """
    Détecte l'angle d'inclinaison du texte et corrige la rotation.
    Ne corrige que les petits angles (< 15°) pour éviter les faux positifs.
    """
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 50:
        return img

    angle = cv2.minAreaRect(coords)[-1]

    # minAreaRect retourne un angle entre -90 et 0
    if angle < -45:
        angle = 90 + angle
    else:
        angle = angle

    # Ne corriger que les petits angles (bruit vs vraie inclinaison)
    if abs(angle) < 0.5 or abs(angle) > 15:
        return img

    h, w = img.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(img, M, (w, h),
                             flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)
    logger.info(f"[enhance] Deskew : {angle:.2f}°")
    return rotated


# ---------------------------------------------------------------------------
# Étape 3 — Amélioration du contraste (CLAHE)
# ---------------------------------------------------------------------------

def _enhance_contrast(img: "np.ndarray") -> "np.ndarray":
    """
    Applique CLAHE (Contrast Limited Adaptive Histogram Equalization) sur le
    canal L de l'espace LAB. Améliore les zones sombres sans brûler les claires.
    """
    import cv2

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_eq = clahe.apply(l)
    lab_eq = cv2.merge([l_eq, a, b])
    result = cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)
    return result


# ---------------------------------------------------------------------------
# Étape 4 — Débruitage
# ---------------------------------------------------------------------------

def _denoise(img: "np.ndarray") -> "np.ndarray":
    """
    Réduit le bruit photographique avec le filtre Non-Local Means d'OpenCV.
    Paramètres conservateurs pour ne pas perdre les détails fins du texte.
    """
    import cv2

    denoised = cv2.fastNlMeansDenoisingColored(img, None,
                                               h=6, hColor=6,
                                               templateWindowSize=7,
                                               searchWindowSize=21)
    return denoised
